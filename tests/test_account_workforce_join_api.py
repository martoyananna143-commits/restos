"""Strict API declaration and boundary tests for existing Account joins."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_workforce_join
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.workforce_invitation_service import (
    InvalidOrUnavailableInvitation,
)


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


class Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def client(monkeypatch):
    session = Session()
    account_id = uuid4()

    async def principal():
        return CurrentAccountPrincipal(account_id, uuid4(), uuid4(), 1, NOW)

    async def database():
        yield session

    from app.api.routers import account_invitation_auth

    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_ALLOWED_ORIGINS",
        ["https://testserver"],
    )
    monkeypatch.setattr(
        account_workforce_join.config,
        "ACCOUNT_AUTH_INVITATION_PEPPER",
        "api-invitation-pepper-at-least-32-bytes",
    )
    monkeypatch.setattr(
        account_workforce_join.config,
        "ACCOUNT_AUTH_PHONE_PEPPER",
        "api-phone-pepper-at-least-32-bytes",
    )
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_workforce_join.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app), session, account_id, app


def headers():
    return {"Origin": "https://testserver", "X-RestOS-Web-Session": "1"}


def test_openapi_is_strict_typed_and_contains_safe_errors(monkeypatch):
    _, _, _, app = client(monkeypatch)
    operation = app.openapi()["paths"][
        "/api/v1/account/workforce/invitations/accept"
    ]["post"]
    assert set(operation["responses"]) >= {"200", "400", "401", "409"}
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["AcceptInvitationRequest"]["additionalProperties"] is False
    assert schemas["AcceptInvitationResponse"]["additionalProperties"] is False
    serialized = str(operation).lower()
    for forbidden in ("phone", "account_id", "token", "cookie", "otp"):
        assert forbidden not in serialized


def test_accept_binds_authenticated_account_and_is_no_store(monkeypatch):
    captured = []

    class Service:
        def __init__(self, *_args):
            pass

        async def accept_authenticated(self, request, phone_pepper):
            captured.append((request, phone_pepper))
            return SimpleNamespace()

        async def acceptance_projection(self, _accepted):
            return SimpleNamespace(
                company_name="Synthetic Company",
                position_name="Synthetic Position",
                venue_names=("Synthetic Venue",),
            )

    monkeypatch.setattr(
        account_workforce_join, "WorkforceInvitationService", Service
    )
    http, session, account_id, _ = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/account/workforce/invitations/accept",
            json={"invitation_code": "123456"},
            headers=headers(),
        )
    assert response.status_code == 200 and response.json() == {
        "joined": True,
        "company_name": "Synthetic Company",
        "position_name": "Synthetic Position",
        "venue_names": ["Synthetic Venue"],
    }
    assert captured[0][0].account_id == account_id
    assert captured[0][0].code == "123456"
    assert session.commits == 1 and session.rollbacks == 0
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers


def test_unknown_field_web_boundary_and_unavailable_are_controlled(monkeypatch):
    class Service:
        def __init__(self, *_args):
            pass

        async def accept_authenticated(self, _request, _phone_pepper):
            raise InvalidOrUnavailableInvitation("database details")

    monkeypatch.setattr(
        account_workforce_join, "WorkforceInvitationService", Service
    )
    http, session, _, _ = client(monkeypatch)
    path = "/api/v1/account/workforce/invitations/accept"
    with http:
        extra = http.post(
            path,
            json={"invitation_code": "123456", "phone": "+79991234567"},
            headers=headers(),
        )
        boundary = http.post(path, json={"invitation_code": "123456"})
        unavailable = http.post(
            path, json={"invitation_code": "123456"}, headers=headers()
        )
    assert extra.status_code == 422
    assert boundary.status_code == 403
    assert unavailable.status_code == 400 and session.rollbacks == 1
    assert unavailable.json() == {
        "detail": {"code": "invitation_unavailable"}
    }
    assert "database details" not in unavailable.text
    assert unavailable.headers["cache-control"] == "private, no-store"
