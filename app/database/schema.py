"""Static DDL strings for the app's Postgres schema. Kept here, separate from
migrations.py, so the SQL itself is easy to find/review without wading through
connection-handling code.
"""

CREATE_URLS_TABLE = """
CREATE TABLE IF NOT EXISTS urls (
    id BIGSERIAL PRIMARY KEY,
    short_code VARCHAR(32) UNIQUE NOT NULL,
    long_url TEXT NOT NULL,
    is_custom_alias BOOLEAN NOT NULL DEFAULT FALSE,
    click_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);
"""
