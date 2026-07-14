"""
Hotelier Panel - Redis cache helpers.

Key pattern: hmspro:hotelier-panel:cache:{db_name}:{resource}[:{variant}]

  hmspro            - top-level product namespace, shared across all microservices
  hotelier-panel    - this microservice; prevents collision with booking-engine, pms, etc.
  cache             - distinguishes cached data from rate-limit, celery, JWT keys
  {db_name}         - per-tenant isolation; hotel-jaljeera never touches hotel-abc
  {resource}        - what data it holds
  [{variant}]       - optional: gen, list:{hash}, dropdown, all, serviceable, etc.
"""

import json
import time

from app.database.redis_client import RedisClient

from app.config.settings import settings

_redis = RedisClient(settings.redis_url)


# ── TTLs (seconds) ────────────────────────────────────────────────────────────

TTL_AMENITIES = 3_600  #  1 h - amenity/facility catalogue changes rarely
TTL_ROOMS = 1_800  # 30 m - room list refreshed on any room mutation
TTL_BED_TYPES = 7_200  #  2 h - bed type options are very stable
TTL_ROOM_CATEGORIES = 7_200  #  2 h - category list is stable
TTL_ROOM_VIEWS = 7_200  #  2 h - view options are stable
TTL_MEAL_PLANS = 3_600  #  1 h - meal plan catalogue
TTL_BASE_PRICING = 1_800  # 30 m - pricing can change; keep short
TTL_PRICING_RULES = 1_800  # 30 m - rule-based pricing
TTL_POLICIES = 7_200  #  2 h - policy templates change only on explicit save
TTL_TAXES = 3_600  #  1 h - tax rules change infrequently
TTL_USERS = 300  #  5 m - user data is sensitive; keep short
TTL_ROLES = 1_800  # 30 m - role definitions
TTL_TENANTS = (
    300  #  5 m - per-user property list; invalidated on property create/invite/remove
)

# Generation key lifetime - must exceed every data TTL so a gen key never
# expires before its data keys do (which would cause stale "gen-0" data to be
# served on the next miss).
_TTL_GEN = 86_400  # 24 h


# ── Key builders ──────────────────────────────────────────────────────────────


class CacheKeys:
    """Single source of truth for every hotelier-panel cache namespace."""

    _BASE = "hmspro:hotelier-panel:cache"

    @classmethod
    def _ns(cls, db_name: str, resource: str) -> str:
        return f"{cls._BASE}:{db_name}:{resource}"

    @classmethod
    def amenities(cls, db_name: str) -> str:
        return cls._ns(db_name, "amenities")

    @classmethod
    def rooms(cls, db_name: str) -> str:
        return cls._ns(db_name, "rooms")

    @classmethod
    def bed_types(cls, db_name: str) -> str:
        return cls._ns(db_name, "bed_types")

    @classmethod
    def room_categories(cls, db_name: str) -> str:
        return cls._ns(db_name, "room_categories")

    @classmethod
    def room_views(cls, db_name: str) -> str:
        return cls._ns(db_name, "room_views")

    @classmethod
    def meal_plans(cls, db_name: str) -> str:
        return cls._ns(db_name, "meal_plans")

    @classmethod
    def base_pricing(cls, db_name: str) -> str:
        return cls._ns(db_name, "base_pricing")

    @classmethod
    def pricing_rules(cls, db_name: str) -> str:
        return cls._ns(db_name, "pricing_rules")

    @classmethod
    def policies(cls, db_name: str) -> str:
        return cls._ns(db_name, "policies")

    @classmethod
    def taxes(cls, db_name: str) -> str:
        return cls._ns(db_name, "taxes")

    @classmethod
    def users(cls, db_name: str) -> str:
        return cls._ns(db_name, "users")

    @classmethod
    def roles(cls, db_name: str) -> str:
        return cls._ns(db_name, "roles")

    @classmethod
    def tenants(cls, user_id: str) -> str:
        """Per-user list of all properties the user has access to (not scoped to a hotel db)."""
        return f"{cls._BASE}:global:tenants:{user_id}"


# ── Primitive read / write helpers ────────────────────────────────────────────


async def cache_get(key: str):
    """Return deserialized value or None on miss / Redis error."""
    try:
        raw = await _redis.async_get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def cache_set(key: str, value, ttl: int) -> None:
    """Serialize and store value. Silently skips on Redis error - never breaks the API."""
    try:
        await _redis.async_set(key, json.dumps(value, default=str), expire=ttl)
    except Exception:
        pass


async def cache_invalidate(*keys: str) -> None:
    """Best-effort delete; Redis hiccups must not fail the hotelier write."""
    if not settings.redis_url or not keys:
        return
    try:
        await _redis.async_delete(*keys)
    except Exception:
        pass


def _gen_key(namespace: str) -> str:
    return f"{namespace}:gen"


def _list_data_key(namespace: str, gen: str, variant: str) -> str:
    return f"{namespace}:list:{gen}:{variant}"


async def cache_get_list(namespace: str, variant: str):
    """
    Return a cached list response or None on miss / stale generation / error.
    Requires two Redis reads: generation lookup + data lookup.
    """
    gen = await cache_get(_gen_key(namespace))
    if gen is None:
        return None
    return await cache_get(_list_data_key(namespace, gen, variant))


async def cache_set_list(namespace: str, variant: str, value, ttl: int) -> None:
    """
    Store a list response under the current generation.
    Initialises the generation key on the first write for this namespace.
    """
    gen = await cache_get(_gen_key(namespace))
    if gen is None:
        gen = str(int(time.time() * 1000))
        await cache_set(_gen_key(namespace), gen, _TTL_GEN)
    await cache_set(_list_data_key(namespace, gen, variant), value, ttl)


async def invalidate_list_cache(namespace: str, *extra_keys: str) -> None:
    """
    Bump the generation counter to make all current list entries stale, and
    optionally delete additional fixed keys (e.g. standalone dropdown caches).
    Old data keys become unreachable and expire naturally via their TTL.
    """
    new_gen = str(int(time.time() * 1000))
    await cache_set(_gen_key(namespace), new_gen, _TTL_GEN)
    if extra_keys:
        await cache_invalidate(*extra_keys)
