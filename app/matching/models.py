"""Потребности, неизменяемые версии выдачи и отметки внутри потребности."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployerNeed(Base):
    """Текущая редактируемая потребность принадлежит одной компании."""

    __tablename__ = "employer_needs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employer_profiles.id"))
    version: Mapped[int]
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)


class NeedVersion(Base):
    """Редактирование не меняет старую версию потребности."""

    __tablename__ = "employer_need_versions"
    need_id: Mapped[UUID] = mapped_column(
        ForeignKey("employer_needs.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MatchingSnapshot(Base):
    """Закрытая выдача содержит доказательства и версии без контактов."""

    __tablename__ = "matching_snapshots"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("employer_needs.id"))
    need_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    catalog_version: Mapped[str] = mapped_column(String(64))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    ranking: Mapped[dict[str, object]] = mapped_column(JSONB)


class CandidateNeedMark(Base):
    """Сохранение/скрытие относится только к конкретной потребности."""

    __tablename__ = "candidate_need_marks"
    need_id: Mapped[UUID] = mapped_column(
        ForeignKey("employer_needs.id"), primary_key=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), primary_key=True
    )
    saved: Mapped[bool] = mapped_column(default=False)
    hidden: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
