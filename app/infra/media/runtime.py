"""Runtime construction for the backend-only private media adapter."""

from functools import lru_cache

from app.infra.media.s3_private_media_store import (
    MediaStoreUnavailable,
    S3PrivateMediaStore,
    S3PrivateMediaStoreSettings,
)
from app.settings import config


def task_media_enabled() -> bool:
    """Return the fail-closed runtime capability without exposing settings."""
    return (
        config.TASK_MEDIA_PROVIDER.strip().lower() == "s3"
        and config.TASK_MEDIA_S3_SSE == "AES256"
        and all(
            isinstance(value, str) and bool(value.strip())
            for value in (
                config.TASK_MEDIA_S3_ENDPOINT,
                config.TASK_MEDIA_S3_BUCKET,
                config.TASK_MEDIA_S3_ACCESS_KEY_ID,
                config.TASK_MEDIA_S3_SECRET_ACCESS_KEY,
            )
        )
    )


@lru_cache(maxsize=1)
def get_task_media_store() -> S3PrivateMediaStore:
    if not task_media_enabled():
        raise MediaStoreUnavailable("private media storage is unavailable")
    return S3PrivateMediaStore(
        S3PrivateMediaStoreSettings(
            endpoint_url=config.TASK_MEDIA_S3_ENDPOINT,
            bucket=config.TASK_MEDIA_S3_BUCKET,
            region=config.TASK_MEDIA_S3_REGION,
            access_key=config.TASK_MEDIA_S3_ACCESS_KEY_ID,
            secret_key=config.TASK_MEDIA_S3_SECRET_ACCESS_KEY,
            ca_file=config.TASK_MEDIA_S3_CA_FILE,
        )
    )


def clear_task_media_store_cache() -> None:
    get_task_media_store.cache_clear()
