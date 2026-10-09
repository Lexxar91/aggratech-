"""CLI мотивированной обработки апелляций и подтверждённых технических сбоев."""

import argparse
import asyncio
from uuid import UUID

from app.assessment.admin import intervene
from app.core import models  # noqa: F401 — регистрирует FK для отдельного процесса
from app.core.config import Settings
from app.core.database import create_database, create_sessions
from app.notifications.queue import utc_now


async def run(
    cycle: UUID, action: str, reason: str, reviewer: str, seconds: int
) -> None:
    """Выполняет одну служебную операцию с аудитом в общей транзакции."""
    engine = create_database(Settings())
    try:
        async with create_sessions(engine).begin() as db:
            await intervene(
                db,
                cycle,
                action=action,
                reason=reason,
                reviewer=reviewer,
                now=utc_now(),
                seconds=seconds,
            )
    finally:
        await engine.dispose()


def main() -> None:
    """Требует оператора и причину; команды не являются HTTP-доступом кандидата."""
    parser = argparse.ArgumentParser()
    parser.add_argument("cycle", type=UUID)
    parser.add_argument(
        "action", choices=["extend", "retry", "uphold", "invalidate", "review"]
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--seconds", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(run(args.cycle, args.action, args.reason, args.reviewer, args.seconds))


if __name__ == "__main__":
    main()
