"""Security and adapter regressions for private task evidence media."""

import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest

from app.infra.media import (
    MediaStoreUnavailable,
    S3PrivateMediaStore,
    S3PrivateMediaStoreSettings,
)
from app.settings import Config


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _ObjectResponse(BytesIO):
    def release_conn(self):
        return None


class _FakeMinio:
    def __init__(self, *, public: bool = False, encrypted: bool = True):
        self.public = public
        self.encrypted = encrypted
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket):
        return bucket == "task-media-test"

    def get_bucket_policy(self, bucket):
        principal = "*" if self.public else {"AWS": "synthetic-private-principal"}
        return json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": principal,
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    }
                ],
            }
        )

    def put_object(self, bucket, key, stream, length, **_options):
        self.objects[key] = stream.read(length)

    def copy_object(self, bucket, key, source, **_options):
        self.objects[key] = self.objects[source.object_name]

    def remove_object(self, _bucket, key):
        self.objects.pop(key, None)

    def stat_object(self, _bucket, _key):
        metadata = {"X-Amz-Server-Side-Encryption": "AES256"} if self.encrypted else {}
        return SimpleNamespace(metadata=metadata)

    def get_object(self, _bucket, key):
        return _ObjectResponse(self.objects[key])

    def list_objects(self, _bucket, prefix, recursive):
        assert prefix == "temporary/" and recursive is True
        return [
            SimpleNamespace(
                object_name=key,
                last_modified=NOW - timedelta(hours=49),
            )
            for key in self.objects
            if key.startswith(prefix)
        ]


def _store(*, public: bool = False, encrypted: bool = True):
    settings = S3PrivateMediaStoreSettings(
        endpoint_url="https://media.internal.test",
        bucket="task-media-test",
        region="us-east-1",
        access_key="synthetic-access",
        secret_key="synthetic-secret",
    )
    store = S3PrivateMediaStore(settings)
    store._client = _FakeMinio(public=public, encrypted=encrypted)
    return store, settings


@pytest.mark.asyncio
async def test_private_adapter_put_promote_get_delete_and_cleanup_are_bounded():
    store, settings = _store()
    content = b"safe-synthetic-image"
    temporary = "temporary/companies/a/tasks/b/c.png"
    evidence = "evidence/companies/a/tasks/b/c.png"
    await store.verify_security()
    await store.put_temporary(temporary, content, "image/png")
    assert await store.list_temporary(NOW, 10) == [temporary]
    await store.promote(temporary, evidence)
    assert await store.get(evidence, len(content)) == content
    await store.delete(evidence)
    assert not store._client.objects
    representation = repr(settings)
    assert "synthetic-access" not in representation
    assert "synthetic-secret" not in representation


@pytest.mark.asyncio
async def test_private_adapter_rejects_public_bucket_and_missing_sse():
    public, _ = _store(public=True)
    with pytest.raises(MediaStoreUnavailable):
        await public.verify_security()
    unencrypted, _ = _store(encrypted=False)
    with pytest.raises(MediaStoreUnavailable):
        await unencrypted.put_temporary(
            "temporary/companies/a/tasks/b/c.png", b"value", "image/png"
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://media.internal.test",
        "https://user:secret@media.internal.test",
        "https://media.internal.test/private",
        "https://media.internal.test?credential=value",
    ],
)
def test_private_adapter_requires_safe_tls_origin(endpoint):
    with pytest.raises(MediaStoreUnavailable) as caught:
        S3PrivateMediaStoreSettings(
            endpoint_url=endpoint,
            bucket="task-media-test",
            region="us-east-1",
            access_key="synthetic-access",
            secret_key="synthetic-secret",
        ).validated()
    assert endpoint not in str(caught.value)


def test_media_source_contains_no_permissive_serialization_or_sensitive_logging():
    sources = "\n".join(
        [
            open("app/infra/media/s3_private_media_store.py", encoding="utf-8").read(),
            open(
                "app/internal/services/task_media_service.py", encoding="utf-8"
            ).read(),
            open(
                "app/api/routers/account_organization_workflows.py", encoding="utf-8"
            ).read(),
            open("scripts/cleanup_task_media.py", encoding="utf-8").read(),
        ]
    )
    assert "default=str" not in sources
    assert "base64" not in sources
    assert "logger." not in sources and "logging." not in sources
    assert "original_filename" not in sources and ".filename" not in sources
    assert "temporary/" in sources and "evidence/" in sources


def _production_media_environment(monkeypatch, **changes):
    values = {
        "APP_ENV": "production",
        "TGBOT_TOKEN": "synthetic-test-token",
        "TGBOT_ADMIN_IDS": "0",
        "JWT_SECRET_KEY": "j" * 48,
        "WEBAPP_SECRET_KEY": "w" * 64,
        "DEFAULT_ADMIN_PASSWORD": "Strong-Synthetic-Password-42!",
        "INTERNAL_API_KEY": "i" * 48,
        "CORS_ORIGINS": "https://api.example.test",
        "CORS_ALLOW_CREDENTIALS": "true",
        "SMS_PROVIDER": "disabled",
        "ACCOUNT_GROUP_INVITATION_PEPPER": "g" * 48,
        "WEBAUTHN_RP_ID": "example.test",
        "WEBAUTHN_RP_NAME": "RestOS",
        "WEBAUTHN_ALLOWED_ORIGINS": "https://app.example.test",
        "TASK_MEDIA_PROVIDER": "s3",
        "TASK_MEDIA_S3_ENDPOINT": "https://media.example.test",
        "TASK_MEDIA_S3_BUCKET": "task-media-test",
        "TASK_MEDIA_S3_ACCESS_KEY_ID": "synthetic-access-key",
        "TASK_MEDIA_S3_SECRET_ACCESS_KEY": "synthetic-secret-key",
        "TASK_MEDIA_S3_SSE": "AES256",
        "TASK_MEDIA_TEMPORARY_TTL_HOURS": "48",
    }
    values.update(changes)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_production_media_configuration_requires_tls_sse_and_runtime_credentials(
    monkeypatch,
):
    _production_media_environment(monkeypatch)
    Config().validate_production_security()


def test_production_disabled_media_is_valid_without_provider_credentials(monkeypatch):
    _production_media_environment(
        monkeypatch,
        TASK_MEDIA_PROVIDER="disabled",
        TASK_MEDIA_S3_ENDPOINT="",
        TASK_MEDIA_S3_BUCKET="",
        TASK_MEDIA_S3_ACCESS_KEY_ID="",
        TASK_MEDIA_S3_SECRET_ACCESS_KEY="",
    )
    Config().validate_production_security()


def test_path_a_production_example_declares_required_fail_closed_settings():
    values = {}
    with open(".env.production.example", encoding="utf-8") as source:
        for line in source:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                name, value = stripped.split("=", 1)
                values[name] = value

    assert "ACCOUNT_GROUP_INVITATION_PEPPER" in values
    assert values["ACCOUNT_GROUP_INVITATION_PEPPER"].startswith("GENERATE_WITH:")
    assert values["ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED"] == "false"
    assert values["TASK_MEDIA_PROVIDER"] == "disabled"
    assert not any(name.startswith("TASK_MEDIA_S3_") for name in values)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ACCOUNT_GROUP_INVITATION_PEPPER", ""),
        ("TASK_MEDIA_PROVIDER", "filesystem"),
        ("TASK_MEDIA_S3_ENDPOINT", "http://media.example.test"),
        ("TASK_MEDIA_S3_ENDPOINT", "https://user:key@media.example.test"),
        ("TASK_MEDIA_S3_BUCKET", ""),
        ("TASK_MEDIA_S3_ACCESS_KEY_ID", ""),
        ("TASK_MEDIA_S3_SECRET_ACCESS_KEY", ""),
        ("TASK_MEDIA_S3_SSE", "aws:kms"),
        ("TASK_MEDIA_TEMPORARY_TTL_HOURS", "0"),
        ("TASK_MEDIA_TEMPORARY_TTL_HOURS", "49"),
    ],
)
def test_unsafe_production_media_configuration_fails_without_secret_values(
    monkeypatch, name, value
):
    _production_media_environment(monkeypatch, **{name: value})
    with pytest.raises(RuntimeError) as caught:
        Config().validate_production_security()
    message = str(caught.value)
    assert "synthetic-access-key" not in message
    assert "synthetic-secret-key" not in message
