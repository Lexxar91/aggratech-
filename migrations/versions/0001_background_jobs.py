"""Первая схема: сохраняемая очередь и безопасный аудит."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_background_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт очередь и ограничения идемпотентного диагностического эффекта."""
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("deduplication_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("last_error_code", sa.String(64)),
        sa.PrimaryKeyConstraint("id", name="pk_background_jobs"),
        sa.UniqueConstraint(
            "deduplication_key", name="uq_background_jobs_deduplication_key"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_background_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_background_jobs_attempt_count"
        ),
    )
    op.create_index(
        "ix_background_jobs_status_available_at",
        "background_jobs",
        ["status", "available_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(36)),
        sa.Column("safe_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.UniqueConstraint("action", "entity_id", name="uq_audit_events_action"),
    )


def downgrade() -> None:
    """Удаляет только таблицы первой миграции."""
    op.drop_table("audit_events")
    op.drop_index(
        "ix_background_jobs_status_available_at", table_name="background_jobs"
    )
    op.drop_table("background_jobs")
