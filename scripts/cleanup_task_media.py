"""Delete expired private task-media uploads without exposing object names."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.media import get_task_media_store
from app.internal.services.task_media_service import TaskMediaService
from app.settings import config


async def cleanup(limit: int) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=config.TASK_MEDIA_TEMPORARY_TTL_HOURS)
    store = get_task_media_store()
    await store.verify_security()
    orphan_keys = set(await store.list_temporary(cutoff, limit))

    engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    deleted = 0
    finalized = 0
    try:
        async with factory() as session:
            claimed = await TaskMediaService(session).claim_expired_pending(
                cutoff, now, limit
            )
            await session.commit()
            claimed_by_key = {item.object_key: item for item in claimed}
            for object_key in sorted(orphan_keys | claimed_by_key.keys()):
                await store.delete(object_key)
                deleted += 1
                item = claimed_by_key.get(object_key)
                if item is not None:
                    await TaskMediaService(session).finalize_delete(
                        item.company_id, item.photo_id, datetime.now(timezone.utc)
                    )
                    await session.commit()
                    finalized += 1
    finally:
        await engine.dispose()
    return deleted, finalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup expired private task media")
    parser.add_argument("--limit", type=int, default=100)
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    deleted, finalized = asyncio.run(cleanup(arguments.limit))
    print(f"task_media_cleanup deleted={deleted} finalized={finalized}")


if __name__ == "__main__":
    main()
