from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateProfile(Base):
    """Профиль владельца; имя и настройки видимости не являются публичной DTO."""

    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint(
            "(salary_min IS NULL AND salary_max IS NULL) OR "
            "(salary_min IS NOT NULL AND salary_max IS NOT NULL "
            "AND salary_min >= 0 AND salary_max >= salary_min)",
            name="salary_range",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    experience: Mapped[str] = mapped_column(Text, default="")
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_basis: Mapped[str] = mapped_column(String(16), default="gross")
    available_from: Mapped[date | None] = mapped_column(Date)
    preferences_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    privacy: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    work_preferences: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=0)


class CandidateContact(Base):
    """Закрытые контакты, доступные только владельцу на этапе 2."""

    __tablename__ = "candidate_contacts"
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(32), default="")
    messengers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidateTechnology(Base):
    """Только заявленная технология, не доказательство assessment."""

    __tablename__ = "candidate_technologies"
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), primary_key=True
    )
    technology_id: Mapped[UUID] = mapped_column(
        ForeignKey("technologies.id"), primary_key=True
    )
    declared: Mapped[bool] = mapped_column(default=True)


class CandidateEmployerBlock(Base):
    """Текущее закрытие видимости кандидата конкретному работодателю."""

    __tablename__ = "candidate_employer_blocks"
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), primary_key=True
    )
    employer_id: Mapped[UUID] = mapped_column(
        ForeignKey("employer_profiles.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
