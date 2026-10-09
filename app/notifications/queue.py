import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import AuditEvent, BackgroundJob


class DuplicateJobConflict(ValueError):
    """Один ключ задания не может обозначать разные действия."""


@dataclass(frozen=True)
class ClaimedJob:
    """Неизменяемый снимок задания, захваченного одним worker."""

    id: UUID
    kind: str
    payload: dict[str, object]
    claim_token: UUID
    attempt_count: int


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict[str, object],
    deduplication_key: str,
    now: datetime,
) -> UUID:
    """Ставит задание в транзакции вызывающей операции, проверяя повтор ключа."""
    if not 1 <= len(kind) <= 64 or not 1 <= len(deduplication_key) <= 160:
        raise ValueError("invalid_job_key")
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    if len(encoded.encode()) > 262144:
        raise ValueError("job_payload_too_large")
    job_id = uuid4()
    result = await session.scalar(
        insert(BackgroundJob)
        .values(
            id=job_id,
            kind=kind,
            payload=payload,
            deduplication_key=deduplication_key,
            status="queued",
            attempt_count=0,
            available_at=now,
        )
        .on_conflict_do_nothing(index_elements=["deduplication_key"])
        .returning(BackgroundJob.id)
    )
    if result is not None:
        return result
    existing = (
        await session.scalars(
            select(BackgroundJob).where(
                BackgroundJob.deduplication_key == deduplication_key
            )
        )
    ).one()
    if existing.kind != kind or existing.payload != payload:
        raise DuplicateJobConflict("idempotency_conflict")
    return existing.id


async def claim(
    session: AsyncSession, *, now: datetime, lease_seconds: int, max_attempts: int
) -> ClaimedJob | None:
    """Атомарно захватывает задание и восстанавливает просроченную обработку."""
    expired = and_(BackgroundJob.status == "running", BackgroundJob.lease_until <= now)
    await session.execute(
        update(BackgroundJob)
        .where(expired, BackgroundJob.attempt_count >= max_attempts)
        .values(
            status="failed",
            lease_until=None,
            claim_token=None,
            last_error_code="lease_exhausted",
        )
    )
    job = (
        await session.scalars(
            select(BackgroundJob)
            .where(
                or_(
                    and_(
                        BackgroundJob.status == "queued",
                        BackgroundJob.available_at <= now,
                    ),
                    expired,
                ),
                BackgroundJob.attempt_count < max_attempts,
            )
            .order_by(BackgroundJob.available_at, BackgroundJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).first()
    if job is None:
        return None
    token = uuid4()
    job.status = "running"
    job.attempt_count += 1
    job.claim_token = token
    job.lease_until = now + timedelta(seconds=lease_seconds)
    job.last_error_code = None
    await session.flush()
    return ClaimedJob(job.id, job.kind, job.payload, token, job.attempt_count)


async def owned_job(
    session: AsyncSession, job: ClaimedJob, now: datetime
) -> BackgroundJob | None:
    """Блокирует запись только для действующего владельца обработки."""
    return (
        await session.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == job.id,
                BackgroundJob.status == "running",
                BackgroundJob.claim_token == job.claim_token,
                BackgroundJob.lease_until > now,
            )
            .with_for_update()
        )
    ).first()


async def finish_diagnostic(
    session: AsyncSession, job: ClaimedJob, now: datetime
) -> bool:
    """Фиксирует реальный диагностический эффект и завершение в одной транзакции."""
    row = await owned_job(session, job, now)
    if row is None:
        return False
    await session.execute(
        insert(AuditEvent)
        .values(
            id=uuid4(),
            action="diagnostic_completed",
            entity_type="background_job",
            entity_id=job.id,
            safe_metadata={"attempt_count": job.attempt_count},
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["action", "entity_id"])
    )
    row.status = "succeeded"
    row.claim_token = None
    row.lease_until = None
    return True


async def fail(
    session: AsyncSession,
    job: ClaimedJob,
    *,
    now: datetime,
    max_attempts: int,
    error_code: str,
    retryable: bool,
) -> bool:
    """Записывает безопасную причину и ограниченный повтор без потери задания."""
    row = await owned_job(session, job, now)
    if row is None:
        return False
    retry = retryable and row.attempt_count < max_attempts
    row.status = "queued" if retry else "failed"
    row.available_at = now + timedelta(seconds=min(2**row.attempt_count, 60))
    row.claim_token = None
    row.lease_until = None
    row.last_error_code = error_code
    return True


async def queue_size(session: AsyncSession) -> int:
    """Возвращает число ожидающих и выполняемых заданий."""
    value = await session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(BackgroundJob.status.in_(("queued", "running")))
    )
    return value or 0


def utc_now() -> datetime:
    """Возвращает UTC-время для производственного worker."""
    return datetime.now(UTC)
