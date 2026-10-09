"""Контактное согласие принадлежит профилю, а не публичной карточке."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.candidate_profile.models import (
    CandidateContact,
    CandidateEmployerBlock,
    CandidateProfile,
)
from app.core.database import Base
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.notifications.models import AuditEvent
from app.notifications.queue import utc_now


class ContactGrant(Base):
    """Разрешение одной пары с единственным источником: приглашение или отклик."""

    __tablename__ = "contact_grants"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(invitation_id, application_id) = 1", name="one_source"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidate_profiles.id"))
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employer_profiles.id"))
    invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("invitations.id"), unique=True
    )
    application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id"), unique=True
    )
    allowed_fields: Mapped[list[str]] = mapped_column(JSONB)
    consent_version: Mapped[str] = mapped_column(String(32))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SharedContacts(BaseModel):
    """Не выбранные поля отсутствуют в выдаче и PDF."""

    model_config = ConfigDict(extra="forbid")
    email: str | None = None
    phone: str | None = None
    messengers: dict[str, str] | None = None


async def revoke(
    db: AsyncSession,
    candidate_id: UUID,
    employer_id: UUID | None = None,
    *,
    actor_id: UUID | None = None,
) -> None:
    """Закрывает все источники пары; вызывается под блокировкой профиля."""
    query = update(ContactGrant).where(
        ContactGrant.candidate_id == candidate_id, ContactGrant.revoked_at.is_(None)
    )
    if employer_id is not None:
        query = query.where(ContactGrant.employer_id == employer_id)
    result = await db.execute(
        query.values(revoked_at=utc_now()).returning(ContactGrant.id)
    )
    for identifier in result.scalars():
        db.add(
            AuditEvent(
                actor_id=actor_id,
                action="contacts_revoked",
                entity_type="contact_grant",
                entity_id=identifier,
                safe_metadata={},
                created_at=utc_now(),
            )
        )


async def read_contacts(
    db: AsyncSession, candidate_id: UUID, employer_user: UUID
) -> SharedContacts:
    """На каждом чтении проверяет действующее согласие, блокировку и владельца."""
    profile = await db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.id == candidate_id)
        .with_for_update()
    )
    employer = await db.scalar(
        select(EmployerProfile).where(
            EmployerProfile.user_id == employer_user, EmployerProfile.status == "active"
        )
    )
    if not profile or not employer or not profile.consented_at:
        raise ApiError(404, "contacts_unavailable", "Нет разрешения на контакты.")
    blocked = await db.get(CandidateEmployerBlock, (candidate_id, employer.id))
    if blocked:
        raise ApiError(404, "contacts_unavailable", "Нет разрешения на контакты.")
    grants = list(
        await db.scalars(
            select(ContactGrant).where(
                ContactGrant.candidate_id == candidate_id,
                ContactGrant.employer_id == employer.id,
                ContactGrant.revoked_at.is_(None),
            )
        )
    )
    if not grants:
        raise ApiError(404, "contacts_unavailable", "Нет разрешения на контакты.")
    fields = {field for grant in grants for field in grant.allowed_fields}
    contacts = await db.get(CandidateContact, candidate_id)
    if not contacts:
        raise ApiError(404, "contacts_unavailable", "Контакты недоступны.")
    return SharedContacts(
        email=contacts.email if "email" in fields else None,
        phone=contacts.phone if "phone" in fields else None,
        messengers=contacts.messengers if "messengers" in fields else None,
    )
