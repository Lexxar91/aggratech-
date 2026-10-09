import argparse
import asyncio

from sqlalchemy import select

from app.core.config import Settings
from app.core.database import create_database, create_sessions
from app.notifications.models import AuditEvent, BackgroundJob
from app.notifications.queue import enqueue, utc_now


async def run(key: str) -> None:
    """Ставит диагностическое действие и показывает сохраняемый результат."""
    engine = create_database(Settings())
    sessions = create_sessions(engine)
    try:
        async with sessions.begin() as session:
            job_id = await enqueue(
                session,
                kind="diagnostic",
                payload={},
                deduplication_key=key,
                now=utc_now(),
            )
        async with sessions() as session:
            job = await session.get(BackgroundJob, job_id)
            effects = list(
                await session.scalars(
                    select(AuditEvent.id).where(AuditEvent.entity_id == job_id)
                )
            )
            if job is not None:
                print(f"job_id={job_id} status={job.status} effects={len(effects)}")
    finally:
        await engine.dispose()


def main() -> None:
    """Запускает диагностику очереди по стабильному ключу повторной операции."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.key))


if __name__ == "__main__":
    main()
