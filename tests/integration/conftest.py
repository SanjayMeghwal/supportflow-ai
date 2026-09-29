"""Integration-suite conftest: creates and tears down all database tables
before/after the entire integration test session, ensuring a clean slate
that is completely isolated from the development database.

This conftest supplements the root-level conftest.py fixtures (client,
db_session, test_*_user) and adds session-scoped table management needed
by integration tests that verify database state directly.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.core.config import settings
from backend.app.models.base import Base  # declarative base with all models


# ---------------------------------------------------------------------------
# Session-scoped engine that creates all tables once per integration run
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", autouse=True)
async def integration_db_tables():
    """Create all ORM tables in the test database before the session starts.

    Uses NullPool to avoid cross-event-loop connection sharing issues on
    Windows with asyncpg. Tables are NOT dropped after the session so that
    failures can be inspected. Each test uses independent data (unique UUIDs)
    so stale rows from previous runs do not interfere with assertions.
    """
    engine = create_async_engine(
        settings.async_test_database_url,
        poolclass=NullPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield
