import asyncpg
from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.modules.url_shortner.schemas import UrlShortnerBodySchemas
from app.modules.url_shortner.helper import generate_short_code
from app.database.postgres_client import get_postgres_client


async def short_url(request: Request, params: UrlShortnerBodySchemas):
    client = await get_postgres_client()

    if params.custom_alias:
        short_code = params.custom_alias
        is_custom_alias = True
        insert_query = """
            INSERT INTO urls (short_code, long_url, is_custom_alias, expires_at)
            VALUES ($1, $2, $3, NOW() + ($4 * INTERVAL '1 second'))
            RETURNING id, short_code, long_url, created_at, expires_at
        """
        query_args = (short_code, str(params.url), is_custom_alias, params.ttl)
    else:
        next_id, short_code = await generate_short_code(client)
        insert_query = """
            INSERT INTO urls (id, short_code, long_url, is_custom_alias, expires_at)
            VALUES ($1, $2, $3, FALSE, NOW() + ($4 * INTERVAL '1 second'))
            RETURNING id, short_code, long_url, created_at, expires_at
        """
        query_args = (next_id, short_code, str(params.url), params.ttl)

    try:
        inserted_data = await client.fetch_one(insert_query, *query_args)
    except asyncpg.UniqueViolationError:
        return {
            "status": False,
            "message": f"Alias '{short_code}' is already taken, please choose another one.",
            "status_code": 409,
        }

    return {
        "status": True,
        "message": "Url shorted successfully.",
        "data": jsonable_encoder(inserted_data),
        "status_code": 201,
    }


async def get_url_stats(short_code: str) -> dict:
    client = await get_postgres_client()
    row = await client.fetch_one(
        """
        SELECT short_code, long_url, is_custom_alias, click_count, created_at, expires_at
        FROM urls
        WHERE short_code = $1
        """,
        short_code,
    )

    if row is None:
        return {
            "status": False,
            "message": "This short link doesn't exist.",
            "status_code": 404,
        }

    return {
        "status": True,
        "message": "Stats fetched successfully.",
        "data": jsonable_encoder(row),
        "status_code": 200,
    }
