"""Демонстрационная привязка ФСП, отдельно от подтверждённой квалификации."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FspLink(Base):
    """Кэш mock-хроники хранит явное происхождение и подтверждение владельца."""

    __tablename__ = "fsp_links"
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), primary_key=True
    )
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(32), default="fsp_mock")
    status: Mapped[str] = mapped_column(String(32), default="linked")
    achievements: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
