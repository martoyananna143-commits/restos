"""Strict HTTP/OpenAPI tests for first Owner/Company onboarding."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_first_company
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.first_company_service import FirstCompanyUnavailable


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
        return CurrentAccountPrincipal(account_id, uuid4(), uuid4(), 3, NOW)

    async def database():
        yield session

    from app.api.routers import account_invitation_auth

    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_ALLOWED_ORIGINS",
        ["https://testserver"],
    )
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_first_company.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app), session, account_id, app


def headers():
    return {"Origin": "https://testserver", "X-RestOS-Web-Session": "1"}


def result(created=True):
    return SimpleNamespace(
        created=created,
        company_id=uuid4(),
        company_name="Synthetic Company",
        company_code="company-synthetic",
        employee_profile_id=uuid4(),
        position_id=uuid4(),
        access_profile_id=uuid4(),
        employee_assignment_id=uuid4(),
        venue_id=None,
    )


def test_openapi_is_strict_typed_and_documents_safe_errors(monkeypatch):
    http, _, _, app = make_client(monkeypatch)
    operation = app.openapi()["paths"]["/api/v1/account/companies/first"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("FirstCompanyResponse")
    assert {"401", "403", "409", "422"}.issubset(operation["responses"])
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["CreateFirstCompanyRequest"]["additionalProperties"] is False
    assert schemas["FirstCompanyResponse"]["additionalProperties"] is False
    serialized = str(operation).lower()
    for forbidden in ("phone", "password", "token", "cookie", "answer"):
        assert forbidden not in serialized
    assert http is not None


def test_create_passes_authenticated_account_and_security_version(monkeypatch):
    expected = result()
    captured = []

    class Service:
        def __init__(self, _session):
            pass

        async def create(self, request):
            captured.append(request)
            return expected

    monkeypatch.setattr(account_first_company, "FirstCompanyService", Service)
    http, session, account_id, _ = make_client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/account/companies/first",
            json={
                "company_name": "Synthetic Company",
                "venue_name": None,
                "timezone": "Europe/Moscow",
                "locale": "ru-RU",
            },
            headers=headers(),
        )
    assert response.status_code == 200 and session.commits == 1
    assert captured[0].account_id == account_id
    assert captured[0].expected_security_version == 3
    assert response.json()["relationship"] == "owner"
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers


def test_unknown_fields_and_missing_web_boundary_are_rejected(monkeypatch):
    http, session, _, _ = make_client(monkeypatch)
    with http:
        unknown = http.post(
            "/api/v1/account/companies/first",
            json={"company_name": "Synthetic", "owner_account_id": str(uuid4())},
            headers=headers(),
        )
        boundary = http.post(
            "/api/v1/account/companies/first",
            json={"company_name": "Synthetic"},
        )
    assert unknown.status_code == 422
    assert boundary.status_code == 403
    assert session.commits == 0
    assert "set-cookie" not in unknown.headers and "set-cookie" not in boundary.headers


def test_controlled_unavailable_rolls_back_without_enumeration(monkeypatch):
    class Service:
        def __init__(self, _session):
            pass

        async def create(self, _request):
            raise FirstCompanyUnavailable("internal aggregate distinction")

    monkeypatch.setattr(account_first_company, "FirstCompanyService", Service)
    http, session, _, _ = make_client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/account/companies/first",
            json={"company_name": "Synthetic"},
            headers=headers(),
        )
    assert response.status_code == 409 and session.rollbacks == 1
    assert response.json() == {"detail": {"code": "company_onboarding_unavailable"}}
    assert response.headers["cache-control"] == "private, no-store"
