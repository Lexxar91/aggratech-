from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Vacancy(Base):
    """Редактируемая опубликованная вакансия, закрытие необратимо."""

    __tablename__ = "vacancies"
    __table_args__ = (
        CheckConstraint("status IN ('published','closed')", name="status"),
        CheckConstraint(
            "salary_from > 0 AND salary_to >= salary_from "
            "AND salary_to < 'Infinity'::numeric",
            name="salary",
        ),
        CheckConstraint("currency = 'RUB' AND salary_basis = 'gross'", name="currency"),
        Index("ix_vacancies_employer_status", "employer_id", "status", "published_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employer_profiles.id"))
    need_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_needs.id"))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    salary_from: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    salary_to: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    salary_basis: Mapped[str] = mapped_column(String(8), default="gross")
    conditions: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)


class Application(Base):
    """Одна подача на вакансию; неизменяемый снимок не зависит от её редактирования."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("vacancy_id", "candidate_id"),
        CheckConstraint(
            "status IN ('submitted','viewed','accepted','rejected','withdrawn')",
            name="status",
        ),
        Index("ix_applications_vacancy_status", "vacancy_id", "status", "submitted_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    vacancy_id: Mapped[UUID] = mapped_column(ForeignKey("vacancies.id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidate_profiles.id"))
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employer_profiles.id"))
    vacancy_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
