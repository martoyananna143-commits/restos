"""Strict HTTP boundary tests for authenticated private task media."""

from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_invitation_auth, account_organization_workflows
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.infra.media import MediaStoreUnavailable
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.task_media_service import (
    AuthorizedTaskPhoto,
    DeleteTaskPhoto,
    ReservedTaskPhoto,
)


NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x04\x00\x01\x9e\x91\x9e\xe7"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
WEB_HEADERS = {"Origin": "https://testserver", "X-RestOS-Web-Session": "1"}


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail = False

    async def verify_security(self):
        if self.fail:
            raise MediaStoreUnavailable("private media storage is unavailable")

    async def put_temporary(self, key, content, _mime_type):
        self.objects[key] = content

    async def promote(self, temporary, final):
        self.objects[final] = self.objects.pop(temporary)

    async def get(self, key, _max_bytes):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)


def photo_payload(photo_id, task_id, assignment_id, status="ready"):
    return {
        "photo_id": photo_id,
        "task_id": task_id,
        "task_assignment_id": assignment_id,
        "mime_type": "image/png",
        "byte_size": len(PNG),
        "status": status,
    }


def make_client(monkeypatch):
    session = FakeSession()
    store = FakeStore()
    account_id = uuid4()
    state: dict[str, object] = {}

    async def principal():
        return CurrentAccountPrincipal(account_id, uuid4(), uuid4(), 1, NOW)

    async def database():
        yield session

    class Service:
        def __init__(self, _session):
            pass

        async def reserve(self, command):
            state["reserve"] = command
            photo_id = uuid4()
            digest = hashlib.sha256(PNG).digest()
            return ReservedTaskPhoto(
                photo_id,
                f"temporary/companies/a/tasks/b/{photo_id.hex}.png",
                f"evidence/companies/a/tasks/b/{photo_id.hex}.png",
                "image/png",
                PNG,
                digest,
            )

        async def mark_ready(self, company_id, photo_id, digest, now, final_key):
            state["ready"] = (company_id, digest, now, final_key)
            return photo_payload(photo_id, state["task_id"], state["assignment_id"])

        async def list_photos(self, actor, company, task, assignment, now):
            state["list"] = (actor, company, task, assignment, now)
            return [photo_payload(state["photo_id"], task, assignment)]

        async def authorize_download(self, actor, company, photo, now, *, task_id):
            state["download"] = (actor, company, photo, now, task_id)
            return AuthorizedTaskPhoto(
                state["object_key"], "image/png", len(PNG), hashlib.sha256(PNG).digest()
            )

        async def begin_delete(self, actor, company, task, photo, now):
            state["delete"] = (actor, company, task, photo, now)
            return DeleteTaskPhoto(
                photo_payload(photo, task, state["assignment_id"], "ready"),
                state["object_key"],
                False,
            )

        async def finalize_delete(self, company, photo, now):
            return photo_payload(
                photo, state["task_id"], state["assignment_id"], "deleted"
            )

    monkeypatch.setattr(account_organization_workflows, "TaskMediaService", Service)
    monkeypatch.setattr(
        account_organization_workflows, "get_task_media_store", lambda: store
    )
    monkeypatch.setattr(
        account_organization_workflows, "task_media_enabled", lambda: True
    )
    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_ALLOWED_ORIGINS",
        ["https://testserver"],
    )
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_organization_workflows.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app, raise_server_exceptions=False), session, store, state


def test_upload_list_download_delete_are_typed_no_store_and_cookie_free(monkeypatch):
    http, session, store, state = make_client(monkeypatch)
    company_id, task_id, assignment_id = uuid4(), uuid4(), uuid4()
    state.update(
        {
            "task_id": task_id,
            "assignment_id": assignment_id,
            "photo_id": uuid4(),
            "object_key": "evidence/companies/a/tasks/b/synthetic.png",
        }
    )
    with http:
        uploaded = http.post(
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos?task_assignment_id={assignment_id}",
            files={"photo": ("ignored-original.png", PNG, "image/png")},
            headers=WEB_HEADERS,
        )
        assert uploaded.status_code == 201
        uploaded_body = uploaded.json()
        photo_id = uploaded_body["photo_id"]
        state["photo_id"] = photo_id
        state["object_key"] = next(iter(store.objects))
        listed = http.get(
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos?task_assignment_id={assignment_id}"
        )
        downloaded = http.get(
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{photo_id}/content"
        )
        deleted = http.delete(
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{photo_id}",
            headers=WEB_HEADERS,
        )
    assert listed.status_code == downloaded.status_code == deleted.status_code == 200
    assert listed.json()[0]["photo_id"] == photo_id
    assert downloaded.content == PNG
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert deleted.json()["status"] == "deleted"
    assert session.commits == 3 and session.rollbacks == 0
    for response in (uploaded, listed, downloaded, deleted):
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
        serialized = response.text
        for forbidden in ("object_key", "sha256", "temporary/", "evidence/"):
            assert forbidden not in serialized


def test_storage_failure_is_controlled_503_and_rolls_back(monkeypatch):
    http, session, store, state = make_client(monkeypatch)
    store.fail = True
    state.update({"task_id": uuid4(), "assignment_id": uuid4()})
    response = http.post(
        f"/api/v1/account/companies/{uuid4()}/tasks/{state['task_id']}/photos?task_assignment_id={state['assignment_id']}",
        files={"photo": ("ignored.png", PNG, "image/png")},
        headers=WEB_HEADERS,
    )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "workflow_storage_unavailable"}}
    assert response.headers["cache-control"] == "private, no-store"
    assert session.commits == 0 and session.rollbacks == 1
    assert not store.objects


def test_disabled_media_is_typed_and_blocks_required_photo_workflows(monkeypatch):
    http, session, store, _ = make_client(monkeypatch)
    monkeypatch.setattr(
        account_organization_workflows, "task_media_enabled", lambda: False
    )

    def forbidden_service(_session):
        raise AssertionError(
            "workflow service must not be reached while media is disabled"
        )

    monkeypatch.setattr(account_organization_workflows, "_service", forbidden_service)
    company_id, task_id, assignment_id = uuid4(), uuid4(), uuid4()
    requests = [
        (
            "post",
            f"/api/v1/account/companies/{company_id}/tasks",
            {
                "json": {
                    "request_id": str(uuid4()),
                    "venue_id": str(uuid4()),
                    "assessment_attempt_id": None,
                    "title": "Synthetic blocked task",
                    "description": None,
                },
                "headers": WEB_HEADERS,
            },
        ),
        (
            "post",
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/dispatch",
            {
                "json": {
                    "employee_profile_ids": [str(uuid4())],
                    "expected_version": 1,
                },
                "headers": WEB_HEADERS,
            },
        ),
        (
            "post",
            f"/api/v1/account/companies/{company_id}/task-assignments/{assignment_id}/transition",
            {
                "json": {"action": "submit", "expected_version": 1},
                "headers": WEB_HEADERS,
            },
        ),
        (
            "get",
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos",
            {},
        ),
        (
            "post",
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos?task_assignment_id={assignment_id}",
            {
                "files": {"photo": ("synthetic.png", PNG, "image/png")},
                "headers": WEB_HEADERS,
            },
        ),
        (
            "get",
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{uuid4()}/content",
            {},
        ),
        (
            "delete",
            f"/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{uuid4()}",
            {"headers": WEB_HEADERS},
        ),
    ]

    with http:
        capability = http.get("/api/v1/account/task-media/capability")
        responses = [
            getattr(http, method)(path, **kwargs) for method, path, kwargs in requests
        ]

    assert capability.status_code == 200
    assert capability.json() == {"enabled": False}
    assert capability.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in capability.headers
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "workflow_storage_unavailable"}}
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
    assert session.commits == 0 and session.rollbacks == 5
    assert not store.objects
