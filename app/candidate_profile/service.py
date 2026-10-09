from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.candidate_profile.models import (
    CandidateContact,
    CandidateEmployerBlock,
    CandidateProfile,
    CandidateTechnology,
)
from app.candidate_profile.schemas import (
    ContactsInput,
    ContactsView,
    Privacy,
    ProfileInput,
    ProfileView,
    SafeCard,
    WorkPreferences,
)
from app.catalog.models import Technology
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.notifications.models import AuditEvent
from app.notifications.queue import utc_now


async def own_profile(
    db: AsyncSession, user_id: UUID, *, lock: bool = False
) -> CandidateProfile:
    """Ищет профиль только по серверному идентификатору владельца."""
    query = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if not row:
        raise ApiError(404, "profile_missing", "Профиль не найден.")
    return row


async def card(
    db: AsyncSession, profile: CandidateProfile, *, owner: bool = False
) -> SafeCard:
    """Проецирует только разрешённые поля; контактная таблица не читается."""
    technologies = list(
        await db.execute(
            select(Technology.id, Technology.name)
            .join(
                CandidateTechnology, CandidateTechnology.technology_id == Technology.id
            )
            .where(CandidateTechnology.candidate_id == profile.id)
            .order_by(Technology.id)
        )
    )
    from app.assessment.service import published_result

    privacy = Privacy.model_validate(profile.privacy)
    return SafeCard(
        id=profile.id,
        display_name=profile.display_name if owner or privacy.show_name else "Кандидат",
        summary=profile.summary,
        experience=profile.experience,
        salary_min=profile.salary_min,
        salary_max=profile.salary_max,
        salary_basis=profile.salary_basis,
        available_from=profile.available_from,
        work_preferences=WorkPreferences.model_validate(profile.work_preferences),
        technology_ids=[row[0] for row in technologies],
        technology_names=[row[1] for row in technologies],
        assessment=await published_result(db, profile.user_id, owner=owner),
    )


async def view_profile(db: AsyncSession, profile: CandidateProfile) -> ProfileView:
    """Собственный ответ добавляет согласие и настройки к безопасной проекции."""
    result = await card(db, profile, owner=True)
    return ProfileView(
        **result.model_dump(),
        privacy=Privacy.model_validate(profile.privacy),
        preferences_confirmed_at=profile.preferences_confirmed_at,
        consent_version=profile.consent_version,
        consented_at=profile.consented_at,
        version=profile.version,
    )


async def save_profile(
    db: AsyncSession, user_id: UUID, data: ProfileInput
) -> ProfileView:
    """Сохраняет полный ручной ввод и заявленные технологии в одной транзакции."""
    profile = await own_profile(db, user_id, lock=True)
    if data.technology_ids:
        known = set(
            await db.scalars(
                select(Technology.id).where(
                    Technology.id.in_(data.technology_ids), Technology.active.is_(True)
                )
            )
        )
        if known != set(data.technology_ids):
            raise ApiError(
                422, "unknown_technology", "Выберите технологии из справочника."
            )
    for name in (
        "display_name",
        "summary",
        "experience",
        "salary_min",
        "salary_max",
        "salary_basis",
        "available_from",
    ):
        setattr(profile, name, getattr(data, name))
    profile.work_preferences = data.work_preferences.model_dump(mode="json")
    profile.preferences_confirmed_at = utc_now() if data.confirm_preferences else None
    if data.consent_version != profile.consent_version or data.consent_version:
        profile.consent_version = data.consent_version
        profile.consented_at = utc_now() if data.consent_version else None
        if not data.consent_version:
            profile.privacy = {**profile.privacy, "visible_to_employers": False}
        db.add(
            AuditEvent(
                action="profile_consent",
                entity_type="candidate_profile",
                entity_id=uuid4(),
                safe_metadata={
                    "candidate_id": str(profile.id),
                    "consent_version": data.consent_version,
                },
                created_at=utc_now(),
            )
        )
    profile.version += 1
    await db.execute(
        delete(CandidateTechnology).where(
            CandidateTechnology.candidate_id == profile.id
        )
    )
    db.add_all(
        CandidateTechnology(candidate_id=profile.id, technology_id=identifier)
        for identifier in data.technology_ids
    )
    await db.flush()
    return await view_profile(db, profile)


async def contacts(
    db: AsyncSession, profile: CandidateProfile, data: ContactsInput | None = None
) -> ContactsView:
    """Контакты читает и изменяет исключительно владелец."""
    row = await db.get(CandidateContact, profile.id)
    if not row:
        raise ApiError(404, "contacts_missing", "Контакты не найдены.")
    if data:
        row.email = str(data.email)
        row.phone = data.phone
        row.messengers = data.messengers
        row.updated_at = utc_now()
    return ContactsView(
        email=row.email,
        phone=row.phone,
        messengers=row.messengers,
        updated_at=row.updated_at,
    )


async def visible_profile(
    db: AsyncSession, identifier: UUID, employer_user: UUID
) -> CandidateProfile:
    """На каждом чтении проверяет текущую приватность и блокировку компании."""
    employer = await db.scalar(
        select(EmployerProfile).where(EmployerProfile.user_id == employer_user)
    )
    profile = await db.get(CandidateProfile, identifier)
    if (
        not employer
        or not profile
        or not Privacy.model_validate(profile.privacy).visible_to_employers
        or not profile.consented_at
    ):
        raise ApiError(404, "profile_unavailable", "Карточка недоступна.")
    blocked = await db.get(CandidateEmployerBlock, (profile.id, employer.id))
    if blocked:
        raise ApiError(404, "profile_unavailable", "Карточка недоступна.")
    return profile


async def set_block(
    db: AsyncSession, user_id: UUID, employer_id: UUID, *, blocked: bool
) -> None:
    """Блокировка идемпотентна и изменяет текущие права без выдачи контактов."""
    profile = await own_profile(db, user_id, lock=True)
    if not await db.get(EmployerProfile, employer_id):
        raise ApiError(404, "employer_missing", "Компания не найдена.")
    if blocked:
        await db.execute(
            insert(CandidateEmployerBlock)
            .values(
                candidate_id=profile.id, employer_id=employer_id, created_at=utc_now()
            )
            .on_conflict_do_nothing()
        )
    else:
        await db.execute(
            delete(CandidateEmployerBlock).where(
                CandidateEmployerBlock.candidate_id == profile.id,
                CandidateEmployerBlock.employer_id == employer_id,
            )
        )
