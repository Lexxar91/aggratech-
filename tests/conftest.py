import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Предоставляет отдельную настоящую PostgreSQL для интеграционных проверок."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL required: integration checks must use PostgreSQL"
        )
    if "aggratech_test" not in url:
        pytest.fail("Refusing to reset a database without aggratech_test in its URL")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE audit_events, background_jobs"))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
