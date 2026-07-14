from typing import Optional
from contextlib import asynccontextmanager
import asyncpg
from app.config.settings import settings
from app.utils.log_config import log_message


class PostgresClient:
    """
    Async Postgres client backed by asyncpg.
    Uses a SINGLETON connection pool per DSN (no per-request connections),
    """

    _pools: dict = {}

    def __init__(self, database_url: str = settings.database_url):
        self.database_url = database_url

    # ---------- Internal (Singleton pool creator) ----------

    @classmethod
    async def _get_pool(cls, database_url: str) -> asyncpg.Pool:
        if database_url not in cls._pools:
            cls._pools[database_url] = await asyncpg.create_pool(
                dsn=database_url,
                min_size=1,
                max_size=50,
                command_timeout=10,
            )
        return cls._pools[database_url]

    # ---------- Query Methods ----------

    async def execute_one(self, query: str, *args) -> str:
        """Run an INSERT/UPDATE/DELETE (no rows returned).

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Positional values bound to the placeholders.

        Returns:
            str: The driver's status tag, e.g. "UPDATE 3".
        """
        pool = await self._get_pool(self.database_url)
        try:
            return await pool.execute(query, *args)
        except Exception as error:
            log_message(
                f"execute failed: {error} | query: {query} | args: {args}",
                file_name="postgres_client",
                error=True,
            )
            raise

    async def execute_many(self, query: str, args_list: list) -> None:
        """Run the same INSERT/UPDATE query for a batch of argument tuples."""
        pool = await self._get_pool(self.database_url)
        try:
            async with pool.acquire() as connection:
                await connection.executemany(query, args_list)
        except Exception as error:
            log_message(
                f"execute_many failed: {error} | query: {query}",
                file_name="postgres_client",
                error=True,
            )
            raise

    async def fetch_all(self, query: str, *args) -> list[dict]:
        """Run a SELECT and return every matching row.

        Returns:
            list[dict]: One dict per row, keyed by column name.
        """
        pool = await self._get_pool(self.database_url)
        try:
            rows = await pool.fetch(query, *args)
            return [dict(row) for row in rows]
        except Exception as error:
            log_message(
                f"fetch_all failed: {error} | query: {query} | args: {args}",
                file_name="postgres_client",
                error=True,
            )
            raise

    async def fetch_one(self, query: str, *args) -> Optional[dict]:
        """Run a SELECT and return only the first row.

        Returns:
            dict or None: The first row as a dict, or None if no rows matched.
        """
        pool = await self._get_pool(self.database_url)
        try:
            row = await pool.fetchrow(query, *args)
            return dict(row) if row else None
        except Exception as error:
            log_message(
                f"fetch_one failed: {error} | query: {query} | args: {args}",
                file_name="postgres_client",
                error=True,
            )
            raise

    async def fetch_value(self, query: str, *args):
        """Run a SELECT/INSERT ... RETURNING and return a single scalar value.

        Example: fetch_value("INSERT INTO urls (...) VALUES (...) RETURNING id", ...)
        """
        pool = await self._get_pool(self.database_url)
        try:
            return await pool.fetchval(query, *args)
        except Exception as error:
            log_message(
                f"fetch_value failed: {error} | query: {query} | args: {args}",
                file_name="postgres_client",
                error=True,
            )
            raise

    # ---------- Transactions ----------

    @asynccontextmanager
    async def transaction(self):
        """Acquire a connection and wrap it in a transaction for atomic,
        multi-statement operations.

        Example:
            async with client.transaction() as conn:
                await conn.execute("UPDATE ...")
                await conn.execute("INSERT ...")
            # commits on success, rolls back automatically on any exception
        """
        pool = await self._get_pool(self.database_url)
        async with pool.acquire() as connection:
            async with connection.transaction():
                yield connection

    # ---------- Close Methods (optional) ----------

    @classmethod
    async def close_all(cls):
        for pool in cls._pools.values():
            await pool.close()
        cls._pools.clear()


async def get_postgres_client() -> PostgresClient:
    """
    FastAPI dependency.
    SAFE: returns a lightweight wrapper, not a new pool.
    """
    return PostgresClient()
