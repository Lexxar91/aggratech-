import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.notifications.models import AuditEvent, BackgroundJob
from app.notifications.queue import (
    DuplicateJobConflict,
    claim,
    enqueue,
    fail,
    finish_diagnostic,
)
from app.worker import process_one

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


async def add_job(sessions: async_sessionmaker[AsyncSession], key: str) -> UUID:
    async with sessions.begin() as session:
        return await enqueue(
            session, kind="diagnostic", payload={}, deduplication_key=key, now=NOW
        )


async def test_enqueue_rolls_back_with_business_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        await enqueue(
            session,
            kind="diagnostic",
            payload={},
            deduplication_key="rollback",
            now=NOW,
        )
        await session.rollback()
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(BackgroundJob)) == 0
        )


async def test_repeated_enqueue_has_one_identity_and_rejects_changed_payload(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await add_job(sessions, "same")
    assert await add_job(sessions, "same") == first
    with pytest.raises(DuplicateJobConflict):
        async with sessions.begin() as session:
            await enqueue(
                session,
                kind="diagnostic",
                payload={"changed": True},
                deduplication_key="same",
                now=NOW,
            )


async def test_skip_locked_claims_do_not_wait_or_duplicate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await add_job(sessions, "first")
    await add_job(sessions, "second")
    async with sessions.begin() as left:
        first = await claim(left, now=NOW, lease_seconds=60, max_attempts=3)
        async with sessions.begin() as right:
            second = await asyncio.wait_for(
                claim(right, now=NOW, lease_seconds=60, max_attempts=3), timeout=2
            )
            assert first is not None and second is not None
            assert first.id != second.id


async def test_restart_recovers_job_and_fences_old_owner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await add_job(sessions, "restart")
    async with sessions.begin() as session:
        old = await claim(session, now=NOW, lease_seconds=60, max_attempts=3)
    assert old is not None
    async with sessions.begin() as session:
        assert (
            await claim(
                session,
                now=NOW + timedelta(seconds=59),
                lease_seconds=60,
                max_attempts=3,
            )
            is None
        )
    async with sessions.begin() as session:
        new = await claim(
            session, now=NOW + timedelta(seconds=60), lease_seconds=60, max_attempts=3
        )
    assert new is not None and new.id == job_id and new.attempt_count == 2
    async with sessions.begin() as session:
        assert not await finish_diagnostic(session, old, NOW + timedelta(seconds=61))
        assert await finish_diagnostic(session, new, NOW + timedelta(seconds=61))
    async with sessions.begin() as session:
        assert not await finish_diagnostic(session, new, NOW + timedelta(seconds=62))
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        row = await session.get(BackgroundJob, job_id)
        assert row is not None and row.status == "succeeded"


async def test_completion_and_effect_roll_back_together(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await add_job(sessions, "atomic")
    async with sessions.begin() as session:
        job = await claim(session, now=NOW, lease_seconds=60, max_attempts=3)
    assert job is not None
    async with sessions() as session:
        assert await finish_diagnostic(session, job, NOW)
        await session.rollback()
    async with sessions.begin() as session:
        assert await finish_diagnostic(session, job, NOW)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_retries_are_delayed_and_bounded(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await add_job(sessions, "retry")
    async with sessions.begin() as session:
        job = await claim(session, now=NOW, lease_seconds=60, max_attempts=2)
        assert job is not None
        assert await fail(
            session,
            job,
            now=NOW,
            max_attempts=2,
            error_code="runner_unavailable",
            retryable=True,
        )
    async with sessions.begin() as session:
        assert (
            await claim(
                session,
                now=NOW + timedelta(seconds=1),
                lease_seconds=60,
                max_attempts=2,
            )
            is None
        )
        retried = await claim(
            session, now=NOW + timedelta(seconds=2), lease_seconds=60, max_attempts=2
        )
        assert retried is not None
        assert await fail(
            session,
            retried,
            now=NOW + timedelta(seconds=2),
            max_attempts=2,
            error_code="runner_unavailable",
            retryable=True,
        )
    async with sessions() as session:
        row = await session.get(BackgroundJob, job_id)
        assert row is not None and row.status == "failed" and row.attempt_count == 2


async def test_repeated_crashes_exhaust_lease_limit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await add_job(sessions, "crash")
    async with sessions.begin() as session:
        assert await claim(session, now=NOW, lease_seconds=60, max_attempts=1)
    async with sessions.begin() as session:
        assert (
            await claim(
                session,
                now=NOW + timedelta(seconds=60),
                lease_seconds=60,
                max_attempts=1,
            )
            is None
        )
    async with sessions() as session:
        row = await session.get(BackgroundJob, job_id)
        assert row is not None and row.status == "failed"
        assert row.last_error_code == "lease_exhausted"


async def test_worker_handles_diagnostic_and_unknown_kind(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await add_job(sessions, "worker")
    settings = Settings()
    assert await process_one(sessions, settings)
    assert not await process_one(sessions, settings)
    async with sessions.begin() as session:
        job_id = await enqueue(
            session,
            kind="unsupported",
            payload={},
            deduplication_key="unknown",
            now=NOW,
        )
    assert await process_one(sessions, settings)
    async with sessions() as session:
        row = await session.get(BackgroundJob, job_id)
        assert row is not None and row.status == "failed"
        assert row.last_error_code == "unknown_job_kind"


async def test_killed_worker_is_recovered_by_another_process(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await add_job(sessions, "kill-process")
    environment = dict(os.environ)
    environment["APP_DATABASE_URL"] = environment["TEST_DATABASE_URL"]
    environment["APP_JOB_LEASE_SECONDS"] = "5"
    environment["APP_WORKER_POLL_SECONDS"] = "0.1"
    process: asyncio.subprocess.Process | None = None

    async def launch() -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.worker",
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def wait_status(status: str) -> None:
        async with asyncio.timeout(8):
            while True:
                async with sessions() as session:
                    row = await session.get(BackgroundJob, job_id)
                    if row is not None and row.status == status:
                        return
                await asyncio.sleep(0.05)

    try:
        async with sessions.begin() as blocker:
            # Блокируем только эффект после фиксации захвата задания.
            await blocker.execute(
                text("LOCK TABLE audit_events IN ACCESS EXCLUSIVE MODE")
            )
            process = await launch()
            await wait_status("running")
            process.kill()
            await process.wait()
        async with sessions.begin() as session:
            row = await session.get(BackgroundJob, job_id)
            assert row is not None and row.status == "running"
            row.lease_until = NOW
        process = await launch()
        await wait_status("succeeded")
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(AuditEvent)) == 1
            )
            row = await session.get(BackgroundJob, job_id)
            assert row is not None and row.attempt_count == 2
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
