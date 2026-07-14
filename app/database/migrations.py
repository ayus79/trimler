from urllib.parse import urlparse, urlunparse
import asyncpg
from app.config.settings import settings
from app.utils.log_config import log_message
from app.database.schema import CREATE_URLS_TABLE


def _maintenance_dsn(database_url: str) -> str:
    """Swap the DSN's path to Postgres's always-present 'postgres' maintenance
    database. You can't CREATE DATABASE while connected to the database
    you're trying to create (or replace), so this connects elsewhere first.
    """
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


async def ensure_database_exists() -> None:
    """Creates settings.database_name if it doesn't exist yet.

    Uses a raw asyncpg connection (not the pooled PostgresClient) because
    CREATE DATABASE cannot run inside a transaction block, and the target
    database's own pool can't be opened before the database exists.
    """
    target_db = settings.database_name
    admin_dsn = _maintenance_dsn(settings.database_url)

    connection = await asyncpg.connect(dsn=admin_dsn)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if not exists:
            # Identifiers can't be bound as query params ($1) in DDL - target_db
            # comes from our own settings, never user input, so this is safe.
            await connection.execute(f'CREATE DATABASE "{target_db}"')
            log_message(
                f"Created database '{target_db}'", file_name="migrations", info=True
            )
    finally:
        await connection.close()


async def run_migrations() -> None:
    """Creates required tables if they don't already exist."""
    connection = await asyncpg.connect(dsn=settings.database_url)
    try:
        await connection.execute(CREATE_URLS_TABLE)
        log_message(
            "Migrations applied: urls table ensured", file_name="migrations", info=True
        )
    finally:
        await connection.close()


async def run_startup_migrations() -> None:
    """Entry point called once on app startup, before the server accepts traffic."""
    await ensure_database_exists()
    await run_migrations()
