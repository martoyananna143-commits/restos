"""S3-compatible private object storage for task evidence images."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlsplit

from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error
from minio.sse import SseS3
import urllib3


class MediaStoreUnavailable(Exception):
    """Safe storage-boundary failure without provider details."""


@dataclass(frozen=True, repr=False)
class S3PrivateMediaStoreSettings:
    endpoint_url: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    ca_file: str = ""

    def validated(self) -> "S3PrivateMediaStoreSettings":
        endpoint = urlsplit(self.endpoint_url.strip())
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise MediaStoreUnavailable("private media storage is unavailable")
        if (
            not self.bucket
            or not self.region
            or not self.access_key
            or not self.secret_key
        ):
            raise MediaStoreUnavailable("private media storage is unavailable")
        if self.ca_file and not Path(self.ca_file).is_file():
            raise MediaStoreUnavailable("private media storage is unavailable")
        return self

    @property
    def endpoint(self) -> str:
        parsed = urlsplit(self.endpoint_url.strip())
        return parsed.netloc


class S3PrivateMediaStore:
    """Backend-only S3 client with TLS, private-bucket and SSE-S3 checks."""

    def __init__(self, settings: S3PrivateMediaStoreSettings):
        self._settings = settings.validated()
        http_client = None
        if settings.ca_file:
            http_client = urllib3.PoolManager(
                cert_reqs="CERT_REQUIRED",
                ca_certs=settings.ca_file,
            )
        self._client = Minio(
            self._settings.endpoint,
            access_key=self._settings.access_key,
            secret_key=self._settings.secret_key,
            secure=True,
            region=self._settings.region,
            http_client=http_client,
        )
        self._verified = False
        self._verify_lock = asyncio.Lock()

    async def verify_security(self) -> None:
        if self._verified:
            return
        async with self._verify_lock:
            if self._verified:
                return
            try:
                exists = await asyncio.to_thread(
                    self._client.bucket_exists, self._settings.bucket
                )
                if not exists:
                    raise MediaStoreUnavailable("private media storage is unavailable")
                policy = await self._bucket_policy()
            except MediaStoreUnavailable:
                raise
            except Exception as error:
                raise MediaStoreUnavailable(
                    "private media storage is unavailable"
                ) from error
            if policy is not None and _allows_public_read(policy):
                raise MediaStoreUnavailable("private media storage is unavailable")
            self._verified = True

    async def put_temporary(
        self, object_key: str, content: bytes, mime_type: str
    ) -> None:
        await self.verify_security()
        if not object_key.startswith("temporary/"):
            raise MediaStoreUnavailable("private media storage is unavailable")
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._settings.bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type=mime_type,
                sse=SseS3(),
            )
            await self._assert_encrypted(object_key)
        except MediaStoreUnavailable:
            raise
        except Exception as error:
            raise MediaStoreUnavailable("private media upload failed") from error

    async def promote(self, temporary_key: str, final_key: str) -> None:
        await self.verify_security()
        if not temporary_key.startswith("temporary/") or not final_key.startswith(
            "evidence/"
        ):
            raise MediaStoreUnavailable("private media storage is unavailable")
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                self._settings.bucket,
                final_key,
                CopySource(self._settings.bucket, temporary_key),
                sse=SseS3(),
            )
            await self._assert_encrypted(final_key)
            await asyncio.to_thread(
                self._client.remove_object, self._settings.bucket, temporary_key
            )
        except MediaStoreUnavailable:
            raise
        except Exception as error:
            raise MediaStoreUnavailable("private media promotion failed") from error

    async def get(self, object_key: str, max_bytes: int) -> bytes:
        await self.verify_security()
        if not object_key.startswith("evidence/"):
            raise MediaStoreUnavailable("private media storage is unavailable")
        await self._assert_encrypted(object_key)

        def read() -> bytes:
            response = self._client.get_object(self._settings.bucket, object_key)
            try:
                content = response.read(max_bytes + 1)
            finally:
                response.close()
                response.release_conn()
            if len(content) > max_bytes:
                raise MediaStoreUnavailable("private media object is invalid")
            return content

        try:
            return await asyncio.to_thread(read)
        except MediaStoreUnavailable:
            raise
        except Exception as error:
            raise MediaStoreUnavailable("private media download failed") from error

    async def delete(self, object_key: str) -> None:
        await self.verify_security()
        if not object_key.startswith(("temporary/", "evidence/")):
            raise MediaStoreUnavailable("private media storage is unavailable")
        try:
            await asyncio.to_thread(
                self._client.remove_object, self._settings.bucket, object_key
            )
        except Exception as error:
            raise MediaStoreUnavailable("private media delete failed") from error

    async def list_temporary(self, older_than: datetime, limit: int) -> list[str]:
        await self.verify_security()
        if older_than.tzinfo is None or older_than.utcoffset() is None:
            raise MediaStoreUnavailable("private media cleanup boundary is invalid")

        def collect() -> list[str]:
            result: list[str] = []
            for value in self._client.list_objects(
                self._settings.bucket, prefix="temporary/", recursive=True
            ):
                if (
                    value.object_name
                    and value.last_modified is not None
                    and value.last_modified < older_than
                ):
                    result.append(value.object_name)
                    if len(result) >= limit:
                        break
            return result

        try:
            return await asyncio.to_thread(collect)
        except Exception as error:
            raise MediaStoreUnavailable("private media cleanup failed") from error

    async def _bucket_policy(self) -> dict[str, object] | None:
        try:
            raw = await asyncio.to_thread(
                self._client.get_bucket_policy, self._settings.bucket
            )
        except S3Error as error:
            if error.code in {"NoSuchBucketPolicy", "NoSuchPolicy"}:
                return None
            raise
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise MediaStoreUnavailable("private media storage is unavailable")
        return value

    async def _assert_encrypted(self, object_key: str) -> None:
        value = await asyncio.to_thread(
            self._client.stat_object, self._settings.bucket, object_key
        )
        metadata = {
            str(key).casefold(): str(item)
            for key, item in (value.metadata or {}).items()
        }
        if metadata.get("x-amz-server-side-encryption") != "AES256":
            raise MediaStoreUnavailable("private media encryption verification failed")


def _allows_public_read(policy: dict[str, object]) -> bool:
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        return True
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
            continue
        principal = statement.get("Principal")
        public = principal == "*" or (
            isinstance(principal, dict)
            and any(value == "*" for value in principal.values())
        )
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if (
            public
            and isinstance(actions, list)
            and any(action in {"s3:*", "s3:GetObject"} for action in actions)
        ):
            return True
    return False
