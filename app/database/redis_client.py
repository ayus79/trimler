import redis
import redis.asyncio as aioredis
from app.config.settings import settings


class RedisClient:
    """
    Redis Client with async & sync support.
    Uses SINGLETON connection pools per URL (no per-request connections).
    """

    _async_clients: dict = {}
    _sync_clients: dict = {}

    def __init__(self, redis_url: str = settings.redis_url):
        """
        NOTE:
        __init__ no longer creates connections.
        Connections are created lazily and reused.
        """
        self.redis_url = redis_url

    @property
    def async_client(self) -> aioredis.Redis:
        """
        Expose async Redis client for direct operations.
        Used by rate limiter and other modules that need direct Redis access.
        """
        return self._get_async_client(self.redis_url)

    @property
    def sync_client(self) -> redis.Redis:
        """
        Expose sync Redis client for direct operations.
        Used by background jobs and synchronous code.
        """
        return self._get_sync_client(self.redis_url)

    # ---------- Internal (Singleton creators) ----------

    @classmethod
    def _get_async_client(cls, redis_url: str) -> aioredis.Redis:
        if redis_url not in cls._async_clients:
            cls._async_clients[redis_url] = aioredis.from_url(
                redis_url,
                decode_responses=True,
                max_connections=200,  # was 50 - saturated under load-test at concurrency 100
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=True,
            )
        return cls._async_clients[redis_url]

    @classmethod
    def _get_sync_client(cls, redis_url: str) -> redis.Redis:
        if redis_url not in cls._sync_clients:
            cls._sync_clients[redis_url] = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=True,
            )
        return cls._sync_clients[redis_url]

    # ---------- Async Methods ----------

    async def async_set(self, key: str, value: str, expire: int = None):
        client = self._get_async_client(self.redis_url)
        return await client.set(key, value, ex=expire)

    async def async_get(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.get(key)

    async def async_delete(self, *keys: str):
        if not keys:
            return 0
        client = self._get_async_client(self.redis_url)
        return await client.delete(*keys)

    async def async_exists(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.exists(key)

    async def async_publish(self, channel: str, message: str):
        client = self._get_async_client(self.redis_url)
        return await client.publish(channel, message)

    async def async_scan(self, cursor: int = 0, match: str = None, count: int = 10):
        client = self._get_async_client(self.redis_url)
        return await client.scan(cursor=cursor, match=match, count=count)

    async def async_ttl(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.ttl(key)

    async def async_subscribe(self, channel: str):
        client = self._get_async_client(self.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)

        async for msg in pubsub.listen():
            if msg["type"] == "message":
                yield msg["data"]

    # ---------- Standard Redis Async API (JWT-friendly) ----------

    async def setex(self, key: str, time: int, value: str):
        client = self._get_async_client(self.redis_url)
        return await client.setex(key, time, value)

    async def get(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.get(key)

    async def delete(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.delete(key)

    async def exists(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.exists(key)

    async def scan(self, cursor: int = 0, match: str = None, count: int = 10):
        client = self._get_async_client(self.redis_url)
        return await client.scan(cursor=cursor, match=match, count=count)

    async def ttl(self, key: str):
        client = self._get_async_client(self.redis_url)
        return await client.ttl(key)

    # ---------- Sync Methods (background jobs / scripts only) ----------

    def sync_set(self, key: str, value: str, expire: int = None):
        client = self._get_sync_client(self.redis_url)
        return client.set(key, value, ex=expire)

    def sync_get(self, key: str):
        client = self._get_sync_client(self.redis_url)
        return client.get(key)

    def sync_delete(self, *keys: str):
        if not keys:
            return 0
        client = self._get_sync_client(self.redis_url)
        return client.delete(*keys)

    def sync_exists(self, key: str):
        client = self._get_sync_client(self.redis_url)
        return client.exists(key)

    def sync_publish(self, channel: str, message: str):
        client = self._get_sync_client(self.redis_url)
        return client.publish(channel, message)

    def sync_subscribe(self, channel: str):
        client = self._get_sync_client(self.redis_url)
        pubsub = client.pubsub()
        pubsub.subscribe(channel)

        for msg in pubsub.listen():
            if msg["type"] == "message":
                yield msg["data"]

    # ---------- Close Methods (optional) ----------

    @classmethod
    async def close_async(cls):
        for client in cls._async_clients.values():
            await client.close()
        cls._async_clients.clear()

    @classmethod
    def close_sync(cls):
        for client in cls._sync_clients.values():
            client.close()
        cls._sync_clients.clear()


async def get_redis_client() -> RedisClient:
    """
    FastAPI dependency.
    SAFE: returns a lightweight wrapper, not a new connection.
    """
    return RedisClient()
