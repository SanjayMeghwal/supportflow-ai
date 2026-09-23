"""Pytest shared fixtures for SupportFlow AI test suites."""

import uuid
from collections.abc import AsyncGenerator
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import create_access_token, hash_password
from backend.app.main import app
from backend.app.models.user import Customer, User, UserRole

# Test engine targeting the dedicated, isolated test database (supportflow_test_db).
# NullPool prevents cross-loop connection reuse issues on Windows/asyncpg.
# This ensures tests NEVER mutate the development database (supportflow_db).
test_engine = create_async_engine(
    settings.async_test_database_url,
    poolclass=NullPool,
    future=True,
)

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency override providing a clean, non-pooled async database session."""
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client fixture configured against the FastAPI ASGI app."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct async database session using test engine for seeding test data."""
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest_asyncio.fixture
async def test_customer_user(db_session: AsyncSession) -> dict:
    """Fixture creating an active CUSTOMER user with linked Customer profile."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"customer_{unique_id}@example.com"
    raw_password = "CustomerPassword123!"
    user = User(
        email=email,
        hashed_password=hash_password(raw_password),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    customer = Customer(
        user_id=user.id,
        full_name=f"Customer {unique_id}",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(customer)

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )

    return {
        "user": user,
        "customer": customer,
        "email": email,
        "raw_password": raw_password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def test_admin_user(db_session: AsyncSession) -> dict:
    """Fixture creating an active ADMIN user."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"admin_{unique_id}@example.com"
    raw_password = "AdminPassword123!"
    user = User(
        email=email,
        hashed_password=hash_password(raw_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )

    return {
        "user": user,
        "email": email,
        "raw_password": raw_password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def test_agent_user(db_session: AsyncSession) -> dict:
    """Fixture creating an active SUPPORT_AGENT user."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"agent_{unique_id}@example.com"
    raw_password = "AgentPassword123!"
    user = User(
        email=email,
        hashed_password=hash_password(raw_password),
        role=UserRole.SUPPORT_AGENT,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )

    return {
        "user": user,
        "email": email,
        "raw_password": raw_password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def test_inactive_user(db_session: AsyncSession) -> dict:
    """Fixture creating an inactive CUSTOMER user."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"inactive_{unique_id}@example.com"
    raw_password = "InactivePassword123!"
    user = User(
        email=email,
        hashed_password=hash_password(raw_password),
        role=UserRole.CUSTOMER,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )

    return {
        "user": user,
        "email": email,
        "raw_password": raw_password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }
