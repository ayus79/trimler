import time
import uuid
from typing import Optional, Set, Tuple
from redis.exceptions import RedisError
from app.middleware.rate_limiter.utils import _LUA_TOKEN_BUCKET, RateLimitAlgo
from app.database.redis_client import RedisClient


class RateLimiter:
    def __init__(
        self,
        key_prefix: str = "rl",
        trusted_proxies: Optional[Set[str]] = None,
    ):
        self._redis_client: Optional[RedisClient] = None
        self._key_prefix = key_prefix
        self._trusted_proxies: Set[str] = trusted_proxies or set()

    def _get_redis(self):
        if self._redis_client is None:
            self._redis_client = RedisClient()
        return self._redis_client.async_client

    def _prefixed(self, key: str) -> str:
        return f"{self._key_prefix}:{key}"

    def is_trusted_proxy(self, ip: str) -> bool:
        return ip in self._trusted_proxies

    async def allow(
        self,
        *,
        key: str,
        limit: int,
        window: int,
        algo: RateLimitAlgo = RateLimitAlgo.SLIDING_WINDOW,
        enable_bot_detection: bool = False,
    ) -> Tuple[bool, int]:
        """Returns (allowed, remaining_requests_in_window)."""
        pkey = self._prefixed(key)

        try:
            redis = self._get_redis()
            if algo == RateLimitAlgo.SLIDING_WINDOW:
                allowed, remaining = await self._sliding_window(
                    redis, pkey, limit, window
                )
            elif algo == RateLimitAlgo.FIXED_WINDOW:
                allowed, remaining = await self._fixed_window(
                    redis, pkey, limit, window
                )
            elif algo == RateLimitAlgo.TOKEN_BUCKET:
                allowed, remaining = await self._token_bucket(
                    redis, pkey, limit, window
                )
            else:
                raise ValueError(f"Unsupported rate limit algorithm: {algo}")

        except RedisError:
            return True, 0

        if not allowed:
            return False, 0

        if enable_bot_detection:
            try:
                redis = self._get_redis()
                if await self._is_suspicious(redis, pkey):
                    return False, 0
            except RedisError:
                pass  # bot detection failure is non-fatal

        return True, remaining

    # ----------------------------------------------------------------
    # Sliding Window
    # ----------------------------------------------------------------
    async def _sliding_window(
        self, redis, key: str, limit: int, window: int
    ) -> Tuple[bool, int]:
        now = time.time()
        # Unique member prevents concurrent requests at the same timestamp
        # from silently overwriting each other in the sorted set.
        member = f"{now}:{uuid.uuid4().hex}"

        pipe = redis.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window + 1)
        _, _, count, _ = await pipe.execute()

        remaining = max(0, limit - count)
        return count <= limit, remaining

    # ----------------------------------------------------------------
    # Fixed Window
    # ----------------------------------------------------------------
    async def _fixed_window(
        self, redis, key: str, limit: int, window: int
    ) -> Tuple[bool, int]:
        bucket = int(time.time() // window)
        window_key = f"{key}:{bucket}"

        count = await redis.incr(window_key)
        if count == 1:
            await redis.expire(window_key, window)

        remaining = max(0, limit - count)
        return count <= limit, remaining

    # ----------------------------------------------------------------
    # Token Bucket (Lua - fully atomic, single round-trip)
    # ----------------------------------------------------------------
    async def _token_bucket(
        self, redis, key: str, limit: int, window: int
    ) -> Tuple[bool, int]:
        now = time.time()
        result = await redis.eval(_LUA_TOKEN_BUCKET, 1, key, limit, window, now)
        return bool(result[0]), int(result[1])

    # ----------------------------------------------------------------
    # Bot / burst detection - first 3 writes are pipelined
    # ----------------------------------------------------------------
    async def _is_suspicious(self, redis, key: str) -> bool:
        now = time.time()
        burst_key = f"burst:{key}"

        pipe = redis.pipeline(transaction=False)
        pipe.rpush(burst_key, now)
        pipe.ltrim(burst_key, -20, -1)
        pipe.expire(burst_key, 2)
        await pipe.execute()

        timestamps = await redis.lrange(burst_key, 0, -1)
        timestamps = [float(ts) for ts in timestamps]

        return len(timestamps) >= 20 and (timestamps[-1] - timestamps[0]) < 1
