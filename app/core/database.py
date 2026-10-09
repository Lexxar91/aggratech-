from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Базовая модель с предсказуемыми именами ограничений миграций."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def create_database(settings: Settings) -> AsyncEngine:
    """Создаёт ленивый пул PostgreSQL для одного процесса."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"timeout": settings.database_timeout_seconds},
    )


def create_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт независимую сессию для каждой транзакции."""
    return async_sessionmaker(engine, expire_on_commit=False)
