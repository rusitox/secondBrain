import uuid
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import event as sa_event

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.utils.encryption import init_fernet, reset_fernet

TEST_DB_URL = "sqlite+aiosqlite://"  # in-memory
TEST_FERNET_KEY = "UoVz65iZZwomYZKNPeWYK_sCieozQPLoezZuUlQwzis="


def get_test_settings() -> Settings:
    return Settings(
        database_url=TEST_DB_URL,
        database_url_sync="sqlite://",
        app_env="testing",
        debug=False,
        fernet_key=TEST_FERNET_KEY,
    )


# Initialize Fernet with test key at module load time
reset_fernet()
init_fernet(TEST_FERNET_KEY)


test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


# Enable foreign key enforcement in SQLite (required for CASCADE)
@sa_event.listens_for(test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _create_sqlite_tables(connection) -> None:
    """Create tables using raw DDL that SQLite understands."""
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            timezone TEXT DEFAULT 'UTC',
            onboarding_completed INTEGER DEFAULT 0,
            onboarding_step INTEGER DEFAULT 0,
            preferences_json TEXT,
            notion_config_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS identities (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            persona_description TEXT DEFAULT '',
            tone_guidelines TEXT DEFAULT '',
            heuristics TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS integrations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            access_token TEXT DEFAULT '',
            refresh_token TEXT DEFAULT '',
            last_sync_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            sync_enabled INTEGER DEFAULT 1,
            sync_interval_minutes INTEGER DEFAULT 30,
            last_sync_status TEXT,
            last_sync_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            embedding TEXT,
            source TEXT NOT NULL,
            source_id TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_user_source
        ON documents(user_id, source, source_id)
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS commitments (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
            commitment_text TEXT NOT NULL,
            owner TEXT DEFAULT 'unknown',
            due_date TIMESTAMP,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 3,
            notion_page_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key_hash TEXT NOT NULL,
            key_prefix TEXT NOT NULL,
            name TEXT NOT NULL,
            last_used_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _drop_sqlite_tables(connection) -> None:
    for table in ["api_keys", "commitments", "documents", "integrations", "identities", "users"]:
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.fixture
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Create SQLite tables for integration tests."""
    async with test_engine.begin() as conn:
        await conn.run_sync(_create_sqlite_tables)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(_drop_sqlite_tables)


@pytest.fixture
async def db_session(setup_test_db: None) -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_settings] = get_test_settings


@pytest.fixture
async def client(setup_test_db: None) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_user_id() -> uuid.UUID:
    return uuid.uuid4()
