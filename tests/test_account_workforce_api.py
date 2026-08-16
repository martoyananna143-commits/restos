"""Strict API tests for Account-only workforce onboarding."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_workforce
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.account_workforce_onboarding_service import (
    AccountWorkforceOnboardingForbidden,
)


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def make_client(monkeypatch):
    session = FakeSession()
    account_id = uuid4()

    async def principal():
        return CurrentAccountPrincipal(account_id, uuid4(), uuid4(), 2, NOW)

    async def database():
        yield session

    from app.api.routers import account_invitation_auth

    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_ALLOWED_ORIGINS",
        ["https://testserver"],
    )
    monkeypatch.setattr(
        account_workforce.config,
        "ACCOUNT_AUTH_INVITATION_PEPPER",
        "test-invitation-pepper-at-least-32-bytes",
    )
    monkeypatch.setattr(
        account_workforce.config,
        "ACCOUNT_AUTH_PHONE_PEPPER",
        "test-phone-pepper-at-least-32-bytes",
    )
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_workforce.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app), session, account_id, app


def headers():
    return {"Origin": "https://testserver", "X-RestOS-Web-Session": "1"}


def test_openapi_has_two_typed_operations_and_strict_models(monkeypatch):
    _, _, _, app = make_client(monkeypatch)
    paths = app.openapi()["paths"]
    prefix = "/api/v1/account/companies/{company_id}/workforce"
    assert set(path for path in paths if path.startswith(prefix)) == {
        f"{prefix}/venues",
        f"{prefix}/invitations",
    }
    create = paths[f"{prefix}/invitations"]["post"]
    assert create["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("WorkforceInvitationResponse")
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["CreateWorkforceInvitationRequest"]["additionalProperties"] is False
    assert schemas["WorkforceInvitationResponse"]["additionalProperties"] is False
    assert "phone" in schemas["CreateWorkforceInvitationRequest"]["required"]
    serialized = str(schemas["WorkforceInvitationResponse"]).lower()
    for forbidden in ("phone", "otp", "password", "token", "cookie", "answer"):
        assert forbidden not in serialized


def test_create_uses_account_company_and_no_store_without_cookie(monkeypatch):
    captured = []
    expected = SimpleNamespace(
        created=True,
        invitation_id=uuid4(),
        employee_profile_id=uuid4(),
        code="123456",
        expires_at=NOW,
    )

    class Service:
        def __init__(self, _session, _invitation_pepper, _phone_pepper):
            pass

        async def create_invitation(self, command):
            captured.append(command)
            return expected

    monkeypatch.setattr(account_workforce, "AccountWorkforceOnboardingService", Service)
    http, session, account_id, _ = make_client(monkeypatch)
    company_id = uuid4()
    request_id = uuid4()
    with http:
        response = http.post(
            f"/api/v1/account/companies/{company_id}/workforce/invitations",
            json={
                "request_id": str(request_id),
                "employee_name": "Synthetic Employee",
                "phone": "+79991234567",
                "venue_id": None,
            },
            headers=headers(),
        )
    assert response.status_code == 200 and session.commits == 1
    assert captured[0].actor_account_id == account_id
    assert captured[0].company_id == company_id
    assert captured[0].request_id == request_id
    assert captured[0].phone == "+79991234567"
    assert response.json()["invitation_code"] == "123456"
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers


def test_list_venues_is_typed_and_permission_scoped(monkeypatch):
    captured = []
    venue_id = uuid4()

    class Service:
        def __init__(self, _session, _invitation_pepper, _phone_pepper):
            pass

        async def list_venues(self, account_id, company_id, now):
            captured.append((account_id, company_id, now))
            return [{"venue_id": venue_id, "name": "Synthetic Venue"}]

    monkeypatch.setattr(account_workforce, "AccountWorkforceOnboardingService", Service)
    http, _, account_id, _ = make_client(monkeypatch)
    company_id = uuid4()
    with http:
        response = http.get(
            f"/api/v1/account/companies/{company_id}/workforce/venues",
            headers=headers(),
        )
    assert response.status_code == 200
    assert response.json() == [
        {"venue_id": str(venue_id), "name": "Synthetic Venue"}
    ]
    assert captured[0][0:2] == (account_id, company_id)
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers


def test_unknown_fields_boundary_and_forbidden_are_controlled(monkeypatch):
    class Service:
        def __init__(self, _session, _invitation_pepper, _phone_pepper):
            pass

        async def create_invitation(self, _command):
            raise AccountWorkforceOnboardingForbidden("foreign company")

    monkeypatch.setattr(account_workforce, "AccountWorkforceOnboardingService", Service)
    http, session, _, _ = make_client(monkeypatch)
    path = f"/api/v1/account/companies/{uuid4()}/workforce/invitations"
    payload = {
        "request_id": str(uuid4()),
        "employee_name": "Synthetic Employee",
        "phone": "+79991234567",
        "venue_id": None,
    }
    with http:
        unknown = http.post(
            path, json={**payload, "unexpected": "value"}, headers=headers()
        )
        boundary = http.post(path, json=payload)
        forbidden = http.post(path, json=payload, headers=headers())
    assert unknown.status_code == 422
    assert boundary.status_code == 403
    assert forbidden.status_code == 403 and session.rollbacks == 1
    assert forbidden.json() == {"detail": {"code": "permission_denied"}}
    assert "foreign company" not in forbidden.text
    assert forbidden.headers["cache-control"] == "private, no-store"
    assert all("set-cookie" not in item.headers for item in (unknown, boundary, forbidden))
