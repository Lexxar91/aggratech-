import asyncio
import logging
import signal
import smtplib
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment.jobs import expire_due_cycles, process_assessment
from app.core import models  # noqa: F401 — регистрирует FK для отдельного процесса
from app.core.config import Settings
from app.core.database import create_database, create_sessions
from app.core.logging import configure_logging
from app.invitations.service import expire_due
from app.notifications.email import finish_email, send_auth_email, send_invitation_email
from app.notifications.queue import (
    claim,
    fail,
    finish_diagnostic,
    queue_size,
    utc_now,
)

logger = logging.getLogger(__name__)


async def process_one(
    sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> bool:
    """Обрабатывает одно сохраняемое задание с отдельной транзакцией захвата."""
    async with sessions.begin() as session:
        await expire_due_cycles(session)
        await expire_due(session)
        job = await claim(
            session,
            now=utc_now(),
            lease_seconds=settings.job_lease_seconds,
            max_attempts=settings.job_max_attempts,
        )
    if job is None:
        return False
    if job.kind == "assessment_grade":
        await process_assessment(sessions, settings, job)
        return True
    started = perf_counter()
    email_error: str | None = None
    if job.kind in ("auth_email", "invitation_email"):
        try:
            await asyncio.to_thread(
                send_auth_email if job.kind == "auth_email" else send_invitation_email,
                settings,
                job,
            )
        except smtplib.SMTPException, OSError:
            email_error = "smtp_unavailable"
        except ValueError:
            email_error = "invalid_email_job"
    async with sessions.begin() as session:
        if job.kind in ("auth_email", "invitation_email"):
            completed = (
                await finish_email(session, job)
                if email_error is None
                else await fail(
                    session,
                    job,
                    now=utc_now(),
                    max_attempts=settings.job_max_attempts,
                    error_code=email_error,
                    retryable=email_error == "smtp_unavailable",
                )
            )
        elif job.kind == "diagnostic":
            completed = await finish_diagnostic(session, job, utc_now())
        else:
            completed = await fail(
                session,
                job,
                now=utc_now(),
                max_attempts=settings.job_max_attempts,
                error_code="unknown_job_kind",
                retryable=False,
            )
        size = await queue_size(session)
    logger.info(
        "job_finished",
        extra={
            "event": "job_finished" if completed else "job_ownership_lost",
            "job_id": str(job.id),
            "attempt_count": job.attempt_count,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "queue_size": size,
        },
    )
    return True


async def main() -> None:
    """Запускает один worker и корректно останавливает его по сигналу."""
    configure_logging()
    settings = Settings()
    engine = create_database(settings)
    sessions = create_sessions(engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            if not await process_one(sessions, settings):
                try:
                    await asyncio.wait_for(stop.wait(), settings.worker_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
