import asyncio

from alembic import context
from sqlalchemy import Connection

from app.core import models
from app.core.config import Settings
from app.core.database import Base, create_database

target_metadata = Base.metadata
__all__ = ["models"]


def run_sync_migrations(connection: Connection) -> None:
    """Применяет миграции через синхронный адаптер async-соединения."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Выполняет миграции отдельно от запуска API и worker."""
    engine = create_database(Settings())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
