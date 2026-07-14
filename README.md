# Trimler

A URL shortener built with FastAPI, PostgreSQL, and Redis - designed around the same
constraints real link-shortening services (bit.ly, tinyurl) actually deal with: fast
redirects, zero-collision code generation, abuse-resistant writes, and click analytics
that don't slow down the read path.

This isn't just a CRUD app with a shortener bolted on. Every architectural decision below
was made, load-tested, and in one case re-engineered after a real bottleneck was found
under concurrent load - see [Performance](#performance--load-testing) for the numbers and
the debugging story behind them.

## Features

- **Shorten a URL** - auto-generated short codes (base62-encoded, backed by a Postgres
  sequence) with **zero collision risk** and no retry loop, or a **custom alias**
  (`/api/url` with `custom_alias`).
- **Link expiration** - optional TTL in seconds; expired links return `410 Gone` instead
  of redirecting, checked live against the current time on every access (not baked in at
  cache time).
- **Redis cache-aside redirects** - `GET /{code}` checks Redis first, falls back to
  Postgres on a miss, and populates the cache - so a popular link's redirects don't hit
  the database on every click.
- **Click analytics** - total click count per link, exposed via a `/stats` page and a
  JSON API. Counting is decoupled from the request path entirely (see below).
- **Rate limiting** - a sliding-window limiter keyed per `(client IP, path)`, so one
  endpoint being hammered doesn't throttle every other endpoint for that client.
- **Protected API docs** - `/docs`, `/redoc`, and `/openapi.json` sit behind HTTP Basic
  Auth with optional IP allowlisting, fail-closed on any error.
- **Self-provisioning database** - on startup, the app creates its own database and
  schema if they don't already exist (`CREATE DATABASE` + `CREATE TABLE IF NOT EXISTS`),
  so a fresh clone works with just a running Postgres instance.
- **A real UI, not just a JSON API** - a Jinja2-rendered shorten page and stats lookup
  page, both served directly by FastAPI.
- **Health check** - `/health` verifies live connectivity to both Postgres and Redis, not
  just that the process is running.

## Performance & load testing

Every number below was measured against the running app on real Postgres + Redis (not
mocked), verified with more than one tool where it mattered, and re-checked after every
fix - not just claimed.

| Endpoint | Concurrency | Throughput | p95 latency |
|---|---|---|---|
| `GET /{code}` (redirect, cache hit) | 50 | **3,067 req/sec** | 29 ms |
| `GET /{code}` (redirect, cache hit) | 100 | **2,734 req/sec** | 52 ms |
| `GET /api/url/{code}/stats` | 100 | **3,164 req/sec** | 45 ms |
| `POST /api/url` (create, write path) | 95 | **1,521 req/sec** | 56 ms |
| `GET /` (homepage) | 10 | **1,784 req/sec** | 6 ms |

*Single uvicorn worker, local dev hardware (11-core, 18GB RAM) - directional numbers for
architecture validation, not a production SLA. Methodology, tooling, and full results in
the sections below.*

### Finding and fixing a real concurrency bottleneck

Adding the Redis cache-aside layer made redirects ~30% faster at moderate concurrency -
but at concurrency 100, throughput unexpectedly *dropped below the pre-cache baseline*
(2,140 → 1,631 req/sec), a sudden cliff rather than a smooth curve. Rather than accept
that, here's what the investigation looked like:

1. **Ruled out the Postgres connection pool** - `pg_stat_activity` sampled mid-test
   showed the pool mostly idle, not saturated.
2. **Ruled out the Redis connection pool** - raised it 50 → 200 connections, confirmed
   via `INFO clients` that the new ceiling was actually in use, and throughput didn't
   move at all.
3. **Ruled out the benchmarking tool itself** - installed `wrk` (an independent, C-based
   load generator) with a Lua script replicating the same test; it landed within a few
   percent of the Python harness, ruling out client-side GIL contention as the cause.
4. **Isolated the actual cause by controlled experiment** - temporarily disabled the
   per-click Postgres write (a `BackgroundTask` running after every redirect) and
   re-ran the exact same test: throughput more than doubled (1,631 → 3,796 req/sec).
   Confirmed: Starlette keeps a request's underlying task alive until its background
   work also finishes, so at 100-way concurrency, ~200 coroutines (100 redirects + 100
   trailing DB writes) were competing for one event loop's attention - a scheduling
   bottleneck no connection-pool metric would show.
5. **Fixed it** - replaced the per-click Postgres `UPDATE` with a Redis `INCR`
   (sub-millisecond) plus a periodic batch job that flushes accumulated counts into
   Postgres every 5 seconds via `GETDEL` (atomic claim-and-reset, so no click is lost to
   a race). Re-verified live end-to-end: real clicks → Redis counter → flush cycle →
   Postgres `click_count` → reflected correctly in `/stats`.
6. **Result**: concurrency-100 throughput recovered to 2,734 req/sec - a 67.7%
   improvement - landing close to the 3,796 req/sec ceiling measured with click-tracking
   removed entirely. The remaining gap is exactly the one Redis round trip still costs
   per request, the correct trade-off for not silently dropping click data.

## Tech stack

| Layer | Choice |
|---|---|
| API framework | FastAPI + Uvicorn |
| Database | PostgreSQL via `asyncpg` (connection-pooled, async) |
| Cache / counters | Redis via `redis.asyncio` |
| Templating | Jinja2 |
| Config | `pydantic-settings` |

## Architecture notes

- **Short code generation**: instead of a random string + collision-check-and-retry
  loop, codes are derived from `nextval()` on the table's own Postgres sequence,
  base62-encoded. One DB round trip, mathematically zero collisions, and codes grow
  naturally from 1 character as the table grows.
- **Cache-aside, not write-through**: the cache is only populated lazily on a read miss,
  matching real traffic patterns (most links are read far more than they're written).
- **Click counting is fully decoupled from the request path**: no redirect ever performs
  a synchronous-feeling database write. Counts live in Redis and get batched into
  Postgres on a timer, trading a few seconds of eventual consistency for a large,
  measured throughput win under concurrent load.
- **Rate limiting is per-path, not global**: the limiter key is `{ip}:{path}`, so a flood
  of requests to one specific short link doesn't consume the budget for `/api/url` or
  any other short link.

## Project structure

```
app/
  config/          settings (Pydantic), env-driven
  database/        Postgres/Redis clients, startup migrations, click-count flush job
  middleware/       rate limiting, docs auth
  modules/
    url_shortner/   create-link API + shorten-page UI
    url_redirect/   the redirect hot path + error pages
  templates/        Jinja2 UI (shorten page, stats page, error page)
  static/           CSS/JS/favicon
main.py             app assembly, route registration, lifespan (migrations + flush loop)
```

## Getting started

```bash
python -m venv env
source env/bin/activate
pip install -r requirements.txt

# Postgres and Redis must be running locally (see app/config/settings.py for defaults)
uvicorn main:app --port 8090 --reload
```

The app creates its own database and `urls` table on first startup - no manual
migration step required.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/url` | Create a short link (optional `custom_alias`, `ttl`) |
| `GET` | `/{code}` | Redirect to the original URL |
| `GET` | `/api/url/{code}/stats` | Click count and metadata for a link |
| `GET` | `/health` | Liveness + Postgres/Redis connectivity check |
| `GET` | `/` | Shorten-a-link UI |
| `GET` | `/stats` | Look-up-a-link's-stats UI |
