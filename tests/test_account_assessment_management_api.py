"""Account assessment management HTTP/OpenAPI contract tests."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_assessment_management
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import (
    CurrentAccountPrincipal,
)
from tests.test_account_assessment_api import attempt_document


NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def assignment_payload():
    return {
        "id": uuid4(),
        "venue_id": None,
        "status": "assigned",
        "assigned_at": NOW,
        "due_at": None,
        "revoked_at": None,
        "completed_at": None,
        "employee": {
            "employee_profile_id": uuid4(),
            "display_name": "Synthetic employee",
            "position_title": "Pilot position",
        },
        "template": {
            "template_id": uuid4(),
            "template_version_id": uuid4(),
            "name": "Synthetic template",
            "version": 1,
        },
        "progress": {
            "answered_count": 0,
            "required_count": 1,
            "total_count": 1,
            "started_at": None,
            "last_saved_at": None,
            "submitted_at": None,
            "completion": None,
        },
    }


def make_client():
    session = FakeSession()

    async def principal():
        return CurrentAccountPrincipal(uuid4(), uuid4(), uuid4(), 1, NOW)

    async def database():
        yield session

    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_assessment_management.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app, raise_server_exceptions=False), session, app


def test_openapi_has_exact_seven_typed_operations():
    _, _, app = make_client()
    prefix = "/api/v1/account/companies/{company_id}/assessment-management"
    operations = {
        (method, path)
        for path, value in app.openapi()["paths"].items()
        for method in value
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert operations == {
        ("get", f"{prefix}/employees"),
        ("get", f"{prefix}/templates"),
        ("get", f"{prefix}/assignments"),
        ("post", f"{prefix}/assignments"),
        ("post", f"{prefix}/measurements"),
        ("get", f"{prefix}/assignments/{{assignment_id}}"),
        ("post", f"{prefix}/assignments/{{assignment_id}}/revoke"),
    }
    for method, path in operations:
        schema = app.openapi()["paths"][path][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert schema.get("$ref") or schema.get("items", {}).get("$ref")


def test_employee_venue_projection_is_explicit_and_old_client_shape_is_stable(
    monkeypatch,
):
    venue_id = uuid4()

    class Service:
        def __init__(self, _session):
            pass

        async def list_employees(self, *_args, include_venue_ids=False, **_kwargs):
            value = {
                "employee_profile_id": uuid4(),
                "display_name": "Synthetic employee",
                "position_title": "Synthetic position",
                "status": "active",
            }
            if include_venue_ids:
                value["venue_ids"] = [venue_id]
                value["venue_required"] = False
            return [value]

    monkeypatch.setattr(
        account_assessment_management, "AssessmentManagementService", Service
    )
    http, _, _ = make_client()
    company_id = uuid4()
    old_shape = http.get(
        f"/api/v1/account/companies/{company_id}/assessment-management/employees"
    )
    assert old_shape.status_code == 200
    assert "venue_ids" not in old_shape.json()[0]

    compatible = http.get(
        f"/api/v1/account/companies/{company_id}/assessment-management/employees"
        "?include_venue_ids=true"
    )
    assert compatible.status_code == 200
    assert compatible.json()[0]["venue_ids"] == [str(venue_id)]
    assert compatible.json()[0]["venue_required"] is False


def test_public_schemas_exclude_answers_pii_and_scoring_fields():
    _, _, app = make_client()
    schemas = app.openapi()["components"]["schemas"]
    public = {
        name: value
        for name, value in schemas.items()
        if name
        in {
            "EmployeeSummary",
            "TemplateVersionSummary",
            "ManagerAssignmentResponse",
            "AssignmentEmployee",
            "AssignmentTemplate",
            "AssignmentProgress",
            "CompletionReceipt",
            "CreateAssignmentRequest",
            "ManagementError",
            "ManagementErrorDetail",
        }
    }
    assert public
    assert all(value.get("additionalProperties") is False for value in public.values())
    for forbidden in (
        "phone",
        "email",
        "telegram",
        "account_id",
        "answer_document",
        "value_json",
        "passing_value",
        "weight",
        "recommendations",
        "private_key",
        "token",
        "cookie",
    ):
        assert all(
            forbidden not in schema.get("properties", {}) for schema in public.values()
        )


def test_create_rejects_unknown_and_naive_fields_before_service():
    http, session, _ = make_client()
    company_id = uuid4()
    payload = {
        "employee_profile_id": str(uuid4()),
        "template_version_id": str(uuid4()),
        "due_at": "2026-09-01T12:00:00",
        "status": "assigned",
    }
    response = http.post(
        f"/api/v1/account/companies/{company_id}/assessment-management/assignments",
        json=payload,
    )
    assert response.status_code == 422
    assert session.commits == session.rollbacks == 0


@pytest.mark.parametrize("operation", ["create", "measurement", "revoke"])
def test_mutations_are_no_store_and_never_set_cookie(monkeypatch, operation):
    class Service:
        def __init__(self, _session):
            pass

        async def create_assignment(self, _command):
            return assignment_payload()

        async def revoke_assignment(self, *_args):
            value = assignment_payload()
            value["status"] = "revoked"
            value["revoked_at"] = NOW
            return value

        async def start_manager_measurement(self, _command):
            return attempt_document(uuid4())

    monkeypatch.setattr(
        account_assessment_management, "AssessmentManagementService", Service
    )
    http, session, _ = make_client()
    company_id = uuid4()
    if operation == "create":
        response = http.post(
            f"/api/v1/account/companies/{company_id}/assessment-management/assignments",
            json={
                "employee_profile_id": str(uuid4()),
                "template_version_id": str(uuid4()),
                "due_at": None,
            },
        )
    elif operation == "measurement":
        response = http.post(
            f"/api/v1/account/companies/{company_id}/assessment-management/measurements",
            json={
                "employee_profile_id": str(uuid4()),
                "template_version_id": str(uuid4()),
                "venue_id": None,
            },
        )
    else:
        response = http.post(
            f"/api/v1/account/companies/{company_id}/assessment-management/assignments/{uuid4()}/revoke"
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    assert session.commits == 1
