"""Сохраняемые циклы, необратимые показы, ответы и публикации assessment."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AssessmentSurvey(Base):
    """Самоописание перед выбором грейда, не подтверждение навыков."""

    __tablename__ = "assessment_surveys"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    answers: Mapped[dict[str, object]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentCycle(Base):
    """Один цикл с закрытым неизменяемым снимком выбранных материалов."""

    __tablename__ = "assessment_cycles"
    __table_args__ = (
        CheckConstraint("mode IN ('demo','credit')", name="mode"),
        CheckConstraint("grade IN ('junior','middle')", name="grade"),
        CheckConstraint("form IN ('X','Y')", name="form"),
        Index("ix_assessment_cycles_user_created", "user_id", "created_at"),
        Index(
            "uq_assessment_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "state IN ('A','B_ready','B','grading','technical_error')"
            ),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    mode: Mapped[str] = mapped_column(String(16))
    grade: Mapped[str] = mapped_column(String(16))
    form: Mapped[str] = mapped_column(String(1))
    state: Mapped[str] = mapped_column(String(32), default="A")
    outcome: Mapped[str] = mapped_column(String(32), default="insufficient")
    review_state: Mapped[str] = mapped_column(String(16), default="clear")
    terminal_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    a_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    a_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    b_start_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    b_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    b_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    b_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_exempt: Mapped[bool] = mapped_column(default=False)
    seed: Mapped[int]
    methodology: Mapped[str] = mapped_column(String(64))
    evaluator_hash: Mapped[str] = mapped_column(String(64))
    bank_hash: Mapped[str] = mapped_column(String(64))
    admission: Mapped[dict[str, object]] = mapped_column(JSONB)
    materials: Mapped[dict[str, object]] = mapped_column(JSONB)
    result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class FamilyExposure(Base):
    """Показ семейства сохраняется между грейдами и режимами навсегда."""

    __tablename__ = "assessment_exposures"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    family: Mapped[str] = mapped_column(String(4), primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("assessment_cycles.id"))
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentAnswer(Base):
    """Черновик, зафиксированная база и перенос одного связанного доказательства."""

    __tablename__ = "assessment_answers"
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment_cycles.id"), primary_key=True
    )
    # v1 хранит family; v3 хранит task_id. Общая история показов — FamilyExposure.
    family: Mapped[str] = mapped_column(String(32), primary_key=True)
    phase: Mapped[str] = mapped_column(String(1))
    parameter_index: Mapped[int]
    step: Mapped[str] = mapped_column(String(16), default="base")
    revision: Mapped[int] = mapped_column(default=0)
    draft: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    base: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    transfer: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grade_generation: Mapped[int] = mapped_column(default=0)
    grading_status: Mapped[str] = mapped_column(String(24), default="pending")
    scores: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    grading_detail: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class AssessmentPublication(Base):
    """Выбор кандидата; демо и зачётные публикации никогда не смешиваются."""

    __tablename__ = "assessment_publications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("assessment_cycles.id"))
    grade: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentAppeal(Base):
    """Обращение и мотивированное служебное решение без нового кабинета."""

    __tablename__ = "assessment_appeals"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("assessment_cycles.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(128))
