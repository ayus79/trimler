import asyncio

from app.database.postgres_client import PostgresClient
from app.database.redis_client import RedisClient
from app.utils.log_config import log_message

CLICK_KEY_PREFIX = "trimler:clicks:"
FLUSH_INTERVAL_SECONDS = 5
SCAN_BATCH_SIZE = 200


async def flush_click_counts() -> None:
    """Claims accumulated Redis click counters and batches them into Postgres.

    Runs periodically instead of writing to Postgres on every single redirect.
    Uses GETDEL to atomically claim + reset each counter - any increment that
    lands between the GETDEL and the next scan just starts the key fresh at 1
    and gets picked up on the following flush cycle, so no clicks are lost.
    """
    redis = RedisClient().async_client
    client = PostgresClient()

    cursor = 0
    pattern = f"{CLICK_KEY_PREFIX}*"
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=SCAN_BATCH_SIZE)

        for key in keys:
            short_code = key[len(CLICK_KEY_PREFIX):]
            raw_count = await redis.getdel(key)
            if raw_count is None:
                continue

            count = int(raw_count)
            if count <= 0:
                continue

            try:
                await client.execute_one(
                    "UPDATE urls SET click_count = click_count + $1 WHERE short_code = $2",
                    count,
                    short_code,
                )
            except Exception as e:
                log_message(
                    f"click flush failed for '{short_code}' (count={count}): {e}",
                    file_name="click_flush",
                    error=True,
                )

        if cursor == 0:
            break


async def run_click_flush_loop() -> None:
    """Background loop started once at app startup (see main.py lifespan)."""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            await flush_click_counts()
        except Exception as e:
            log_message(f"click flush loop error: {e}", file_name="click_flush", error=True)
