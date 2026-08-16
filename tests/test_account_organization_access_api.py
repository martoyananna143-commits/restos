"""Strict HTTP/OpenAPI tests for owner organization access management."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_organization_access
from app.api.routers import account_invitation_auth
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.account_organization_access_service import (
    OrganizationAccessConflict,
    OrganizationAccessNotFound,
)


NOW = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
WEB_HEADERS = {"Origin": "https://testserver", "X-RestOS-Web-Session": "1"}


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def venue_payload(*, created: bool = True):
    return {
        "created": created,
        "venue_id": uuid4(),
        "name": "Synthetic venue",
        "code": "synthetic-venue",
        "timezone": "Europe/Moscow",
        "status": "active",
    }


def employee_payload():
    return {
        "employee_profile_id": uuid4(),
        "display_name": "Synthetic employee",
        "employment_status": "active",
        "position_id": uuid4(),
        "position_name": "Synthetic position",
        "profile": "venue_manager",
        "venue_ids": [uuid4()],
        "revision": NOW,
        "editable": True,
    }


def make_client(monkeypatch):
    session = FakeSession()

    async def principal():
        return CurrentAccountPrincipal(uuid4(), uuid4(), uuid4(), 1, NOW)

    async def database():
        yield session

    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_ALLOWED_ORIGINS",
        ["https://testserver"],
    )
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_organization_access.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app, raise_server_exceptions=False), session, app


def test_openapi_has_exact_six_typed_operations_and_controlled_errors(monkeypatch):
    _, _, app = make_client(monkeypatch)
    prefix = "/api/v1/account/companies/{company_id}/organization"
    operations = {
        (method, path)
        for path, value in app.openapi()["paths"].items()
        for method in value
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert operations == {
        ("get", f"{prefix}/venues"),
        ("post", f"{prefix}/venues"),
        ("get", f"{prefix}/employees"),
        ("get", f"{prefix}/employees/{{employee_profile_id}}/access"),
        ("put", f"{prefix}/employees/{{employee_profile_id}}/access"),
        ("put", f"{prefix}/employees/{{employee_profile_id}}/position"),
    }
    openapi = app.openapi()
    for method, path in operations:
        success = openapi["paths"][path][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert success.get("$ref") or success.get("items", {}).get("$ref")
        for status_code in ("404", "409", "422"):
            error = openapi["paths"][path][method]["responses"][status_code][
                "content"
            ]["application/json"]["schema"]
            assert error["$ref"].endswith("/OrganizationError")


def test_public_schemas_are_strict_and_do_not_expose_sensitive_or_private_fields(
    monkeypatch,
):
    _, _, app = make_client(monkeypatch)
    schemas = app.openapi()["components"]["schemas"]
    names = {
        "CreateVenueRequest",
        "VenueResponse",
        "EmployeeAccessResponse",
        "ReplaceEmployeeAccessRequest",
        "ReplaceEmployeePositionRequest",
        "OrganizationError",
        "OrganizationErrorDetail",
    }
    public = {name: schemas[name] for name in names}
    assert all(schema.get("additionalProperties") is False for schema in public.values())
    encoded = str(public).casefold()
    for forbidden in (
        "phone",
        "email",
        "token",
        "cookie",
        "password",
        "answer_document",
        "value_json",
        "private_key",
    ):
        assert forbidden not in encoded


def test_unknown_fields_are_rejected_before_service(monkeypatch):
    http, session, _ = make_client(monkeypatch)
    response = http.post(
        f"/api/v1/account/companies/{uuid4()}/organization/venues",
        json={
            "request_id": str(uuid4()),
            "name": "Synthetic venue",
            "timezone": "Europe/Moscow",
            "owner": True,
        },
    )
    assert response.status_code == 422
    assert session.commits == session.rollbacks == 0


@pytest.mark.parametrize("operation", ["venue", "access", "position"])
def test_mutations_are_no_store_cookie_free_and_response_validated(monkeypatch, operation):
    employee = employee_payload()

    class Service:
        def __init__(self, _session):
            pass

        async def create_venue(self, _command):
            return venue_payload()

        async def replace_employee_access(self, _command):
            return employee

        async def replace_employee_position(self, _command):
            return employee

    monkeypatch.setattr(
        account_organization_access, "AccountOrganizationAccessService", Service
    )
    http, session, _ = make_client(monkeypatch)
    company_id = uuid4()
    if operation == "venue":
        response = http.post(
            f"/api/v1/account/companies/{company_id}/organization/venues",
            headers=WEB_HEADERS,
            json={
                "request_id": str(uuid4()),
                "name": "Synthetic venue",
                "timezone": "Europe/Moscow",
            },
        )
    elif operation == "access":
        response = http.put(
            f"/api/v1/account/companies/{company_id}/organization/employees/"
            f"{employee['employee_profile_id']}/access",
            headers=WEB_HEADERS,
            json={
                "profile": "venue_manager",
                "venue_ids": [str(employee["venue_ids"][0])],
                "expected_revision": NOW.isoformat(),
            },
        )
    else:
        response = http.put(
            f"/api/v1/account/companies/{company_id}/organization/employees/"
            f"{employee['employee_profile_id']}/position",
            headers=WEB_HEADERS,
            json={
                "position_id": str(employee["position_id"]),
                "expected_revision": NOW.isoformat(),
            },
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            OrganizationAccessNotFound("private"),
            404,
            "organization_resource_not_found",
        ),
        (
            OrganizationAccessConflict("private"),
            409,
            "organization_revision_conflict",
        ),
    ],
)
def test_controlled_errors_are_safe_and_rollback(monkeypatch, error, status_code, code):
    class Service:
        def __init__(self, _session):
            pass

        async def create_venue(self, _command):
            raise error

    monkeypatch.setattr(
        account_organization_access, "AccountOrganizationAccessService", Service
    )
    http, session, _ = make_client(monkeypatch)
    response = http.post(
        f"/api/v1/account/companies/{uuid4()}/organization/venues",
        headers=WEB_HEADERS,
        json={"request_id": str(uuid4()), "name": "Synthetic venue"},
    )
    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code}}
    assert "private" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    assert session.commits == 0
    assert session.rollbacks == 1
