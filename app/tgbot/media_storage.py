"""Persistent media file_id cache for aiogram_dialog (Redis-backed).

When ``StaticMedia`` (or ``DynamicMedia``) sends a file from disk,
Telegram returns a ``file_id``.  By storing that id we can skip the
upload on every subsequent render — the bot simply passes the
cached ``file_id`` and Telegram serves the file instantly.

The cache is stored in Redis, so ``file_id`` values survive bot restarts.
Each video is uploaded to Telegram **only once** — all future starts
read the cached ids from Redis.

Usage::

    from app.tgbot.media_storage import RedisMediaIdStorage

    storage = RedisMediaIdStorage(redis_dsn="redis://localhost:6379/0")
    setup_dialogs(dp, media_id_storage=storage)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from aiogram.enums import ContentType
from aiogram_dialog.api.entities import MediaId
from aiogram_dialog.api.protocols.media import MediaIdStorageProtocol

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "media_cache:"


def _make_key(path: Optional[str], url: Optional[str], content_type: ContentType) -> str:
    """Build a deterministic Redis key from media parameters."""
    return f"{_REDIS_KEY_PREFIX}{path or ''}:{url or ''}:{content_type}"


class RedisMediaIdStorage(MediaIdStorageProtocol):
    """Cache media ``file_id`` in Redis to avoid repeated uploads.

    File ids persist across bot restarts — each video is uploaded to
    Telegram only once in the entire lifetime of the Redis instance.
    """

    def __init__(self, redis_dsn: str) -> None:
        self._redis_dsn = redis_dsn
        self._redis = None  # lazy init

    async def _get_redis(self):
        """Lazily create / return an aioredis connection."""
        if self._redis is None:
            from redis.asyncio import from_url
            self._redis = from_url(self._redis_dsn, decode_responses=True)
        return self._redis

    async def get_media_id(
        self,
        path: Optional[str],
        url: Optional[str],
        type: ContentType,
    ) -> Optional[MediaId]:
        redis = await self._get_redis()
        key = _make_key(path, url, type)
        try:
            raw = await redis.get(key)
        except Exception as exc:
            logger.warning("Redis GET failed for %s: %s", key, exc)
            return None

        if raw is None:
            return None

        try:
            data = json.loads(raw)
            media_id = MediaId(
                file_id=data["file_id"],
                file_unique_id=data.get("file_unique_id"),
            )
            logger.debug("Media cache HIT (Redis) for %s", path or url)
            return media_id
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupt cache entry for %s: %s", key, exc)
            return None

    async def save_media_id(
        self,
        path: Optional[str],
        url: Optional[str],
        type: ContentType,
        media_id: MediaId,
    ) -> None:
        redis = await self._get_redis()
        key = _make_key(path, url, type)
        data = json.dumps({
            "file_id": media_id.file_id,
            "file_unique_id": media_id.file_unique_id,
        })
        try:
            # No TTL — file_ids don't expire on Telegram's side
            await redis.set(key, data)
            logger.info(
                "Media cache SAVE (Redis): %s → file_id=%s",
                path or url,
                media_id.file_id[:20] + "…",
            )
        except Exception as exc:
            logger.warning("Redis SET failed for %s: %s", key, exc)

    async def close(self) -> None:
        """Close the Redis connection (call on shutdown)."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
