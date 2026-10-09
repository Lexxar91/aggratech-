from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.notifications.models import BackgroundJob
from app.notifications.queue import enqueue, utc_now
from app.worker import process_one


async def test_smtp_failure_retries_without_leaking_token(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions.begin() as db:
        identifier = await enqueue(
            db,
            kind="auth_email",
            payload={
                "email": "private@example.com",
                "token": "private-token",
                "purpose": "verify_email",
            },
            deduplication_key="email-failure",
            now=utc_now(),
        )
    settings = Settings(
        smtp_host="127.0.0.1",
        smtp_port=1,
        database_url=SecretStr("postgresql+asyncpg://unused:unused@localhost/unused"),
    )
    assert await process_one(sessions, settings)
    async with sessions() as db:
        row = await db.get(BackgroundJob, identifier)
        assert (
            row and row.status == "queued" and row.last_error_code == "smtp_unavailable"
        )
        assert row.attempt_count == 1 and row.payload["token"] == "private-token"


async def test_invalid_email_job_fails_without_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions.begin() as db:
        await enqueue(
            db,
            kind="auth_email",
            payload={"purpose": "unknown"},
            deduplication_key="invalid-email",
            now=utc_now(),
        )
    assert await process_one(sessions, Settings())
    async with sessions() as db:
        row = await db.scalar(select(BackgroundJob))
        assert (
            row
            and row.status == "failed"
            and row.last_error_code == "invalid_email_job"
        )
