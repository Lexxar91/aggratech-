"""Переходы сериализуются блокировкой профиля, затем приглашения."""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.candidate_profile.access import ContactGrant
from app.candidate_profile.models import CandidateEmployerBlock, CandidateProfile
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.invitations.models import Invitation
from app.invitations.schemas import Acceptance, InvitationView, SendInput
from app.matching.schemas import Need
from app.matching.service import (
    PRODUCT_METHODS,
    company,
    compute,
    owned_need,
    product_candidates,
)
from app.notifications.models import AuditEvent
from app.notifications.queue import enqueue, utc_now

PENDING = ("sent", "viewed")


async def notify(db: AsyncSession, row: Invitation, now: datetime) -> None:
    """Очередь содержит ссылку и адрес получателя, но не контакты кандидата."""
    candidate = await db.get(CandidateProfile, row.candidate_id)
    employer = await db.get(EmployerProfile, row.employer_id)
    assert candidate and employer
    # При отправке/отзыве письмо кандидату, при ответе — отправителю.
    user_id = (
        candidate.user_id
        if row.status in ("sent", "withdrawn", "expired")
        else employer.user_id
    )
    user = await db.get(User, user_id)
    assert user
    await enqueue(
        db,
        kind="invitation_email",
        payload={
            "email": user.email_normalized,
            "invitation_id": str(row.id),
            "status": row.status,
        },
        deduplication_key=f"invitation:{row.id}:{row.status}",
        now=now,
    )


async def changed(
    db: AsyncSession,
    row: Invitation,
    status: str,
    now: datetime,
    actor_id: UUID | None = None,
) -> None:
    """Переход, аудит и уведомление входят в общую транзакцию."""
    row.status = status
    if status == "viewed":
        row.viewed_at = now
    elif status not in PENDING:
        row.decided_at = now
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action=f"invitation_{status}",
            entity_type="invitation",
            entity_id=row.id,
            safe_metadata={"status": status},
            created_at=now,
        )
    )
    if status != "viewed":
        await notify(db, row, now)


async def normalize(
    db: AsyncSession, row: Invitation, profile: CandidateProfile, now: datetime
) -> None:
    """Срок проверяется перед действием; блокировка не меняет принятую историю."""
    employer = await db.get(EmployerProfile, row.employer_id)
    blocked = await db.get(CandidateEmployerBlock, (row.candidate_id, row.employer_id))
    if row.status in PENDING:
        if not employer or employer.status != "active" or blocked:
            await changed(db, row, "withdrawn", now)
        elif now >= row.expires_at:
            await changed(db, row, "expired", now)


async def view(db: AsyncSession, row: Invitation) -> InvitationView:
    """История не копирует приватные контактные значения."""
    grant = await db.scalar(
        select(ContactGrant).where(
            ContactGrant.invitation_id == row.id, ContactGrant.revoked_at.is_(None)
        )
    )
    profile = await db.get(CandidateProfile, row.candidate_id)
    employer = await db.get(EmployerProfile, row.employer_id)
    blocked = await db.get(CandidateEmployerBlock, (row.candidate_id, row.employer_id))
    return InvitationView.model_validate(
        {
            "id": row.id,
            "employer_id": row.employer_id,
            "candidate_id": row.candidate_id,
            "need_id": row.need_id,
            "status": row.status,
            "offer_snapshot": row.offer_snapshot,
            "sent_at": row.sent_at,
            "viewed_at": row.viewed_at,
            "expires_at": row.expires_at,
            "decided_at": row.decided_at,
            "contact_access": bool(
                grant
                and profile
                and profile.consented_at
                and employer
                and employer.status == "active"
                and not blocked
            ),
        }
    )


async def send(
    db: AsyncSession, user_id: UUID, data: SendInput, *, now: datetime | None = None
) -> InvitationView:
    """Идемпотентно отправляет проверенное предложение без обязательной вакансии."""
    employer = await company(db, user_id)
    await db.refresh(employer, with_for_update=True)
    digest = hashlib.sha256(
        json.dumps(
            data.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    previous = await db.scalar(
        select(Invitation).where(
            Invitation.employer_id == employer.id,
            Invitation.idempotency_key == data.idempotency_key,
        )
    )
    if previous:
        if previous.request_hash != digest:
            raise ApiError(
                409,
                "idempotency_conflict",
                "Ключ уже использован для другого предложения.",
            )
        return await action(db, user_id, "employer", previous.id, None, now=now)
    profile = await db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.id == data.candidate_id)
        .with_for_update()
    )
    if profile is None:
        raise ApiError(404, "candidate_unavailable", "Кандидат недоступен.")
    need_row = await owned_need(db, user_id, data.need_id, lock=True)
    clock = now or utc_now()
    rows = await db.scalars(
        select(Invitation)
        .where(
            Invitation.employer_id == employer.id,
            Invitation.need_id == need_row.id,
            Invitation.candidate_id == profile.id,
            Invitation.status.in_((*PENDING, "accepted")),
        )
        .with_for_update()
    )
    for row in rows:
        await normalize(db, row, profile, clock)
        if row.status in (*PENDING, "accepted"):
            raise ApiError(
                409,
                "active_invitation_exists",
                "Уже есть активное или принятое приглашение по этой потребности.",
            )
    await db.flush()
    offer = data.offer
    need = Need.model_validate(need_row.definition)
    conditions = {
        **need.model_dump(),
        "salary_from": offer.salary_from,
        "salary_to": offer.salary_to,
        "work_formats": offer.work_formats,
        "location": offer.location,
        "desired_start_date": offer.desired_start_date,
        "start_date_required": offer.start_date_required,
        "urgency": "normal",
    }
    effective = Need.model_validate(conditions)
    candidates = [
        c
        for c in await product_candidates(db, employer.id, clock)
        if c.candidate_id == str(profile.id)
    ]
    ranking = compute(effective, candidates, clock, PRODUCT_METHODS)
    if not ranking.recommendations or ranking.recommendations[0].group == "excluded":
        raise ApiError(
            409,
            "candidate_incompatible",
            "Кандидат недоступен или известные условия несовместимы.",
        )
    snapshot: dict[str, object] = {
        "offer": offer.model_dump(mode="json"),
        "company_name": employer.company_name,
        "need_version": need.version,
        "need": need.model_dump(mode="json"),
        "compatibility_group": ranking.recommendations[0].group,
        "notice": "Неизвестные условия требуют уточнения."
        if ranking.recommendations[0].group == "needs_clarification"
        else "Известные условия совместимы.",
    }
    row = Invitation(
        id=uuid4(),
        employer_id=employer.id,
        candidate_id=profile.id,
        need_id=need_row.id,
        idempotency_key=data.idempotency_key,
        request_hash=digest,
        salary_from=offer.salary_from,
        salary_to=offer.salary_to,
        offer_snapshot=snapshot,
        status="sent",
        sent_at=clock,
        expires_at=clock + timedelta(days=7),
    )
    db.add(row)
    await db.flush()
    await changed(db, row, "sent", clock, user_id)
    return await view(db, row)


async def action(
    db: AsyncSession,
    user_id: UUID,
    role: str,
    identifier: UUID,
    target: str | None,
    acceptance: Acceptance | None = None,
    *,
    now: datetime | None = None,
) -> InvitationView:
    """Все действия повторяемы; при гонке возвращается фактический итог."""
    if target not in (
        {None, "viewed", "accepted", "rejected"}
        if role == "candidate"
        else {None, "withdrawn"}
    ):
        raise ApiError(403, "invalid_actor_action", "Действие недоступно этой роли.")
    row = await db.get(Invitation, identifier)
    if row is None:
        raise ApiError(404, "invitation_unavailable", "Приглашение недоступно.")
    profile = await db.get(CandidateProfile, row.candidate_id)
    employer = await db.get(EmployerProfile, row.employer_id)
    if (
        not profile
        or not employer
        or (profile.user_id if role == "candidate" else employer.user_id) != user_id
    ):
        raise ApiError(404, "invitation_unavailable", "Приглашение недоступно.")
    await db.refresh(profile, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    clock = now or utc_now()
    await normalize(db, row, profile, clock)
    if target and row.status in PENDING:
        if target == "accepted":
            if not acceptance or not profile.consented_at:
                raise ApiError(
                    409, "consent_required", "Нужно действующее согласие кандидата."
                )
            await changed(db, row, target, clock, user_id)
            await db.flush()
            grant = ContactGrant(
                id=uuid4(),
                candidate_id=profile.id,
                employer_id=row.employer_id,
                invitation_id=row.id,
                allowed_fields=list(acceptance.allowed_fields),
                consent_version=acceptance.consent_version,
                granted_at=clock,
            )
            db.add(grant)
            db.add(
                AuditEvent(
                    actor_id=user_id,
                    action="contacts_granted",
                    entity_type="contact_grant",
                    entity_id=grant.id,
                    safe_metadata={
                        "allowed_fields": list(acceptance.allowed_fields),
                        "consent_version": acceptance.consent_version,
                    },
                    created_at=clock,
                )
            )
        elif target == "viewed" and row.status == "sent":
            await changed(db, row, target, clock, user_id)
        elif target in ("rejected", "withdrawn"):
            await changed(db, row, target, clock, user_id)
    await db.flush()
    return await view(db, row)


async def listing(db: AsyncSession, user_id: UUID, role: str) -> list[InvitationView]:
    """Список не отмечает предложения просмотренными."""
    query = select(Invitation.id)
    if role == "candidate":
        query = query.join(CandidateProfile).where(CandidateProfile.user_id == user_id)
    else:
        query = query.join(EmployerProfile).where(EmployerProfile.user_id == user_id)
    identifiers = list(
        await db.scalars(
            query.order_by(Invitation.candidate_id, Invitation.id).limit(100)
        )
    )
    return [
        await action(db, user_id, role, identifier, None) for identifier in identifiers
    ]


async def expire_due(db: AsyncSession, *, now: datetime | None = None) -> None:
    """Worker использует тот же порядок блокировок и таблицу переходов."""
    clock = now or utc_now()
    rows = list(
        await db.execute(
            select(Invitation.id, CandidateProfile.user_id)
            .join(CandidateProfile)
            .where(Invitation.status.in_(PENDING), Invitation.expires_at <= clock)
            .order_by(Invitation.candidate_id, Invitation.id)
            .limit(100)
        )
    )
    for identifier, user_id in rows:
        await action(db, user_id, "candidate", identifier, None, now=clock)
