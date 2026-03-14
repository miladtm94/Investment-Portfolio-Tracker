"""Redis cache client with async support."""
import json
from typing import Any, Optional
import redis.asyncio as aioredis
from config import get_settings

settings = get_settings()

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _redis


async def cache_get(key: str) -> Optional[Any]:
    r = await get_redis()
    val = await r.get(key)
    if val is None:
        return None
    return json.loads(val)


async def cache_set(key: str, value: Any, ttl: int = None) -> None:
    r = await get_redis()
    serialized = json.dumps(value, default=str)
    if ttl is None:
        ttl = settings.cache_ttl_seconds
    await r.setex(key, ttl, serialized)


async def cache_delete(key: str) -> None:
    r = await get_redis()
    await r.delete(key)


async def cache_delete_pattern(pattern: str) -> int:
    r = await get_redis()
    keys = await r.keys(pattern)
    if keys:
        return await r.delete(*keys)
    return 0


async def cache_invalidate_user(user_id: str) -> None:
    """Invalidate all cached data for a user."""
    await cache_delete_pattern(f"portfolio:{user_id}:*")
    await cache_delete_pattern(f"analytics:{user_id}:*")
    await cache_delete_pattern(f"tax:{user_id}:*")
