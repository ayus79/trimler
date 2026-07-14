from datetime import datetime, timezone

from app.database.postgres_client import get_postgres_client
from app.database.redis_client import RedisClient
from app.utils.cache_config import cache_get, cache_set

CACHE_TTL_SECONDS = 3600  # 1 hour
CLICK_KEY_PREFIX = "trimler:clicks:"


def _cache_key(short_code: str) -> str:
    return f"trimler:redirect:{short_code}"


async def redirect_url(short_code: str) -> dict:
    cache_key = _cache_key(short_code)
    cached = await cache_get(cache_key)

    if cached is not None:
        return _check_expiry_and_build_response(
            url_id=cached["id"],
            long_url=cached["long_url"],
            expires_at_iso=cached["expires_at"],
        )

    client = await get_postgres_client()
    row = await client.fetch_one(
        "SELECT id, long_url, expires_at FROM urls WHERE short_code = $1", short_code
    )

    if row is None:
        return {
            "status": False,
            "message": "This short link doesn't exist.",
            "status_code": 404,
        }

    expires_at_iso = row["expires_at"].isoformat() if row["expires_at"] else None

    # Populate cache on miss (cache-aside). Best-effort - cache_set already
    # swallows Redis errors, so a cache hiccup never breaks a redirect.
    await cache_set(
        cache_key,
        {"id": row["id"], "long_url": row["long_url"], "expires_at": expires_at_iso},
        ttl=CACHE_TTL_SECONDS,
    )

    return _check_expiry_and_build_response(
        url_id=row["id"], long_url=row["long_url"], expires_at_iso=expires_at_iso
    )


def _check_expiry_and_build_response(url_id: int, long_url: str, expires_at_iso: str | None) -> dict:
    # Expiry is checked against the current time on every access, whether the
    # data came from cache or Postgres, so a link that expires mid-cache-window
    # still correctly 410s instead of serving a stale "still valid" verdict.
    if expires_at_iso:
        expires_at = datetime.fromisoformat(expires_at_iso)
        if expires_at < datetime.now(timezone.utc):
            return {
                "status": False,
                "message": "This short link has expired.",
                "status_code": 410,
            }

    return {"status": True, "data": {"id": url_id, "long_url": long_url}}


async def increment_click_count(short_code: str) -> None:
    """Runs as a BackgroundTask after the redirect response is already sent.

    Increments a Redis counter instead of writing to Postgres per click - a
    periodic flush job (app/database/click_flush.py) batches these into
    Postgres. A synchronous-feeling Postgres UPDATE on every single redirect
    was measured to collapse throughput under high concurrency (a
    BackgroundTask keeps the request's underlying task alive until it
    finishes, and at high concurrency that scheduling pressure dominated);
    a Redis INCR is sub-millisecond and avoids that entirely.
    """
    redis = RedisClient().async_client
    await redis.incr(f"{CLICK_KEY_PREFIX}{short_code}")
