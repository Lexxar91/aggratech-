"""Один Unit of Work для отклика, снимка, согласия и аудита."""

from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.candidate_profile import access
from app.candidate_profile import service as profiles
from app.candidate_profile.models import CandidateEmployerBlock, CandidateProfile
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.matching.service import company, owned_need
from app.notifications.models import AuditEvent
from app.notifications.queue import utc_now
from app.vacancies.models import Application, Vacancy
from app.vacancies.schemas import (
    ApplicationInput,
    ApplicationView,
    VacancyInput,
    VacancyPatch,
    VacancyView,
)


def audit(
    db: AsyncSession, user: UUID, action: str, entity: str, identifier: UUID
) -> None:
    """Аудит содержит переход, без сообщения, контактов и закрытых материалов."""
    db.add(
        AuditEvent(
            actor_id=user,
            action=action,
            entity_type=entity,
            entity_id=identifier,
            safe_metadata={},
            created_at=utc_now(),
        )
    )


async def vacancy_view(db: AsyncSession, row: Vacancy) -> VacancyView:
    """Проецирует опубликованные условия без ORM или данных кандидатов."""
    employer = await db.get(EmployerProfile, row.employer_id)
    return VacancyView.model_validate(
        {
            **row.conditions,
            "id": row.id,
            "employer_id": row.employer_id,
            "company_name": employer.company_name if employer else "",
            "need_id": row.need_id,
            "title": row.title,
            "description": row.description,
            "salary_from": row.salary_from,
            "salary_to": row.salary_to,
            "currency": row.currency,
            "salary_basis": row.salary_basis,
            "status": row.status,
            "published_at": row.published_at,
            "closed_at": row.closed_at,
            "version": row.version,
        }
    )


async def owned_vacancy(
    db: AsyncSession, user: UUID, identifier: UUID, *, lock: bool = False
) -> Vacancy:
    """Идентификатор вакансии не заменяет проверку текущего владельца компании."""
    employer = await company(db, user)
    query = select(Vacancy).where(
        Vacancy.id == identifier, Vacancy.employer_id == employer.id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if not row:
        raise ApiError(404, "vacancy_unavailable", "Вакансия недоступна.")
    return row


def assign(row: Vacancy, data: VacancyInput) -> None:
    """Хранит деньги Decimal отдельно, остальные условия — в безопасном JSON."""
    row.title, row.description = data.title, data.description
    row.salary_from, row.salary_to = data.salary_from, data.salary_to
    row.currency, row.salary_basis, row.need_id = (
        data.currency,
        data.salary_basis,
        data.need_id,
    )
    row.conditions = data.model_dump(
        mode="json",
        exclude={
            "title",
            "description",
            "salary_from",
            "salary_to",
            "currency",
            "salary_basis",
            "need_id",
        },
    )


async def create(db: AsyncSession, user: UUID, data: VacancyInput) -> VacancyView:
    """Создаёт сразу published; неоплаченная или чужая потребность не публикуется."""
    employer = await company(db, user)
    if data.need_id:
        await owned_need(db, user, data.need_id)
    row = Vacancy(
        id=uuid4(),
        employer_id=employer.id,
        status="published",
        published_at=utc_now(),
        version=1,
    )
    assign(row, data)
    db.add(row)
    audit(db, user, "vacancy_published", "vacancy", row.id)
    await db.flush()
    return await vacancy_view(db, row)


async def edit(
    db: AsyncSession, user: UUID, identifier: UUID, patch: VacancyPatch
) -> VacancyView:
    """Редактирует только текущую версию открытой вакансии, без изменения откликов."""
    row = await owned_vacancy(db, user, identifier, lock=True)
    if row.status != "published" or row.version != patch.version:
        raise ApiError(
            409,
            "vacancy_changed",
            "Вакансия закрыта или уже изменена. Обновите страницу.",
        )
    values = (await vacancy_view(db, row)).model_dump(
        exclude={
            "id",
            "employer_id",
            "company_name",
            "status",
            "published_at",
            "closed_at",
            "version",
        }
    )
    values.update(patch.model_dump(exclude={"version"}, exclude_unset=True))
    try:
        data = VacancyInput.model_validate(values)
    except ValidationError:
        raise ApiError(
            422, "invalid_vacancy", "Проверьте зарплату и условия вакансии."
        ) from None
    if data.need_id:
        await owned_need(db, user, data.need_id)
    assign(row, data)
    row.version += 1
    audit(db, user, "vacancy_edited", "vacancy", row.id)
    await db.flush()
    return await vacancy_view(db, row)


async def close(db: AsyncSession, user: UUID, identifier: UUID) -> VacancyView:
    """Закрытие повторяемо; история откликов и их согласия сохраняются."""
    row = await owned_vacancy(db, user, identifier, lock=True)
    if row.status != "closed":
        row.status, row.closed_at = "closed", utc_now()
        row.version += 1
        audit(db, user, "vacancy_closed", "vacancy", row.id)
        await db.flush()
    return await vacancy_view(db, row)


async def listing(db: AsyncSession, user: UUID | None = None) -> list[VacancyView]:
    """Публичный список содержит опубликованные вакансии; собственный — историю."""
    query = select(Vacancy).join(EmployerProfile)
    if user:
        employer = await company(db, user)
        query = query.where(Vacancy.employer_id == employer.id)
    else:
        query = query.where(
            Vacancy.status == "published", EmployerProfile.status == "active"
        )
    rows = await db.scalars(
        query.order_by(Vacancy.published_at.desc(), Vacancy.id).limit(100)
    )
    return [await vacancy_view(db, row) for row in rows]


async def public_view(db: AsyncSession, identifier: UUID) -> VacancyView:
    """Закрытая вакансия доступна по ссылке с явным состоянием, без новой подачи."""
    row = await db.scalar(
        select(Vacancy)
        .join(EmployerProfile)
        .where(Vacancy.id == identifier, EmployerProfile.status == "active")
    )
    if not row:
        raise ApiError(404, "vacancy_unavailable", "Вакансия недоступна.")
    return await vacancy_view(db, row)


async def application_view(
    db: AsyncSession, row: Application, user: UUID, role: str
) -> ApplicationView:
    """Контакты читаются отдельно; история повторно проверяет текущую приватность."""
    profile = await db.get(CandidateProfile, row.candidate_id)
    employer = await db.get(EmployerProfile, row.employer_id)
    grant = await db.scalar(
        select(access.ContactGrant).where(access.ContactGrant.application_id == row.id)
    )
    blocked = await db.get(CandidateEmployerBlock, (row.candidate_id, row.employer_id))
    active = bool(
        grant
        and not grant.revoked_at
        and profile
        and profile.consented_at
        and employer
        and employer.status == "active"
        and not blocked
    )
    card = None
    if profile:
        if role == "candidate":
            card = await profiles.card(db, profile, owner=True)
        else:
            try:
                visible = await profiles.visible_profile(db, row.candidate_id, user)
                card = await profiles.card(db, visible)
            except ApiError as error:
                if error.code != "profile_unavailable":
                    raise
    return ApplicationView.model_validate(
        dict(
            id=row.id,
            vacancy_id=row.vacancy_id,
            candidate_id=row.candidate_id,
            employer_id=row.employer_id,
            status=row.status,
            vacancy_snapshot=VacancyView.model_validate(row.vacancy_snapshot),
            message=row.message,
            submitted_at=row.submitted_at,
            updated_at=row.updated_at,
            version=row.version,
            contact_access=active,
            allowed_fields=list(grant.allowed_fields) if active and grant else [],
            candidate_card=card,
            card_notice=None
            if card
            else "Карточка недоступна по текущим настройкам приватности.",
        )
    )


async def apply(
    db: AsyncSession, user: UUID, vacancy_id: UUID, data: ApplicationInput
) -> ApplicationView:
    """Профиль → вакансия; уникальная подача, её снимок и согласие атомарны."""
    profile = await profiles.own_profile(db, user, lock=True)
    existing = await db.scalar(
        select(Application).where(
            Application.vacancy_id == vacancy_id, Application.candidate_id == profile.id
        )
    )
    if existing:
        # Отзыв/закрытие не восстанавливает разрешение при повторном HTTP-запросе.
        return await application_view(db, existing, user, "candidate")
    vacancy = await db.scalar(
        select(Vacancy).where(Vacancy.id == vacancy_id).with_for_update()
    )
    employer = await db.get(EmployerProfile, vacancy.employer_id) if vacancy else None
    if not vacancy or not employer or employer.status != "active":
        raise ApiError(404, "vacancy_unavailable", "Вакансия недоступна.")
    if vacancy.status != "published":
        raise ApiError(409, "vacancy_closed", "Вакансия закрыта для новых откликов.")
    blocked = await db.get(CandidateEmployerBlock, (profile.id, vacancy.employer_id))
    if not profile.consented_at or blocked:
        raise ApiError(
            409,
            "consent_required",
            "Нет действующего согласия на взаимодействие с компанией.",
        )
    now = utc_now()
    row = Application(
        id=uuid4(),
        vacancy_id=vacancy.id,
        candidate_id=profile.id,
        employer_id=vacancy.employer_id,
        vacancy_snapshot=(await vacancy_view(db, vacancy)).model_dump(mode="json"),
        message=data.message,
        status="submitted",
        submitted_at=now,
        updated_at=now,
        version=1,
    )
    db.add(row)
    await db.flush()
    grant = access.ContactGrant(
        id=uuid4(),
        candidate_id=profile.id,
        employer_id=row.employer_id,
        application_id=row.id,
        allowed_fields=list(data.allowed_fields),
        consent_version=data.consent_version,
        granted_at=now,
    )
    db.add(grant)
    audit(db, user, "application_submitted", "application", row.id)
    audit(db, user, "contacts_granted", "contact_grant", grant.id)
    await db.flush()
    return await application_view(db, row, user, "candidate")


async def owned_application(
    db: AsyncSession, user: UUID, role: str, identifier: UUID
) -> Application:
    """Проверяет владельца; порядок блокировок совпадает с приглашениями."""
    row = await db.get(Application, identifier)
    profile = await db.get(CandidateProfile, row.candidate_id) if row else None
    employer = await db.get(EmployerProfile, row.employer_id) if row else None
    if (
        not row
        or not profile
        or not employer
        or (profile.user_id if role == "candidate" else employer.user_id) != user
        or (role == "employer" and employer.status != "active")
    ):
        raise ApiError(404, "application_unavailable", "Отклик недоступен.")
    await db.refresh(profile, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    return row


async def action(
    db: AsyncSession, user: UUID, role: str, identifier: UUID, target: str | None
) -> ApplicationView:
    """Отзывает один источник; решение работодателя не подменяет согласие."""
    if target not in (
        {None, "withdrawn"}
        if role == "candidate"
        else {None, "viewed", "accepted", "rejected"}
    ):
        raise ApiError(403, "invalid_actor_action", "Действие недоступно этой роли.")
    row = await owned_application(db, user, role, identifier)
    if target and target != row.status:
        if target != "withdrawn" and row.status not in ("submitted", "viewed"):
            raise ApiError(
                409, "invalid_application_transition", "Отклик уже завершён."
            )
        row.status, row.updated_at = target, utc_now()
        row.version += 1
        if target == "withdrawn":
            grant = await db.scalar(
                select(access.ContactGrant).where(
                    access.ContactGrant.application_id == row.id,
                    access.ContactGrant.revoked_at.is_(None),
                )
            )
            if grant:
                grant.revoked_at = row.updated_at
                audit(db, user, "contacts_revoked", "contact_grant", grant.id)
        audit(db, user, f"application_{target}", "application", row.id)
        await db.flush()
    return await application_view(db, row, user, role)


async def applications(
    db: AsyncSession, user: UUID, role: str, vacancy_id: UUID | None = None
) -> list[ApplicationView]:
    """История ограничена владельцем и текущей доступностью карточки."""
    if role == "candidate":
        profile = await profiles.own_profile(db, user)
        query = select(Application).where(Application.candidate_id == profile.id)
    else:
        if vacancy_id is None:
            raise ValueError("vacancy_required")
        row = await owned_vacancy(db, user, vacancy_id)
        query = select(Application).where(Application.vacancy_id == row.id)
    rows = await db.scalars(
        query.order_by(Application.submitted_at.desc(), Application.id).limit(100)
    )
    return [await application_view(db, row, user, role) for row in rows]
