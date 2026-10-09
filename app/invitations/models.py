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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Invitation(Base):
    """Снимок условий никогда не редактируется при переходе состояния."""

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('sent','viewed','accepted','rejected','expired','withdrawn')",
            name="status",
        ),
        CheckConstraint(
            "salary_from > 0 AND salary_to >= salary_from "
            "AND salary_to < 'Infinity'::numeric",
            name="salary",
        ),
        CheckConstraint("expires_at = sent_at + interval '7 days'", name="lifetime"),
        UniqueConstraint("employer_id", "idempotency_key"),
        Index(
            "uq_invitations_active",
            "employer_id",
            "need_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("status IN ('sent','viewed','accepted')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employer_profiles.id"))
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidate_profiles.id"))
    need_id: Mapped[UUID] = mapped_column(ForeignKey("employer_needs.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    salary_from: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    salary_to: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    offer_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
