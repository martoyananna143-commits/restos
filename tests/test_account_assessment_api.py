"""Account assessment HTTP/OpenAPI boundary tests."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_assessments, account_invitation_auth
from app.internal.services.account_access_token_service import CurrentAccountPrincipal


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)
ACCOUNT_ID = uuid4()


class FakeSession:
    commits = 0
    rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def attempt_document(attempt_id):
    return {
        "id": attempt_id,
        "assignment_id": uuid4(),
        "status": "draft",
        "revision": 1,
        "started_at": NOW,
        "last_saved_at": NOW,
        "submitted_at": None,
        "read_only": False,
        "read_only_reason": None,
        "document": {"version_id": uuid4(), "sections": []},
        "answers": [],
        "ui_metadata": {"section_order": []},
    }


def assignment_summary(assignment_id=None):
    return {
        "id": assignment_id or uuid4(),
        "company_id": uuid4(),
        "venue_id": None,
        "status": "assigned",
        "assigned_at": NOW,
        "due_at": None,
        "submitted_at": None,
        "template_name": "Employee-safe assessment",
        "template_version": 1,
        "read_only": False,
    }


def assignment_detail(assignment_id=None):
    return {
        **assignment_summary(assignment_id),
        "document": {"version_id": uuid4(), "sections": []},
    }


def completion_result():
    return {
        "scoring_algorithm": "completion_v1",
        "submitted_at": NOW,
        "answered_count": 1,
        "required_count": 1,
        "total_count": 2,
    }


def make_client(monkeypatch):
    session = FakeSession()

    async def principal():
        return CurrentAccountPrincipal(ACCOUNT_ID, uuid4(), uuid4(), 1, NOW)

    async def database():
        yield session

    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_assessments.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[account_invitation_auth.get_account_auth_session] = (
        database
    )
    return TestClient(app, raise_server_exceptions=False), session, app


def test_openapi_exposes_exact_seven_bearer_operations(monkeypatch):
    _, _, app = make_client(monkeypatch)
    operations = {
        (method, path)
        for path, value in app.openapi()["paths"].items()
        for method in value
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert operations == {
        ("get", "/api/v1/account/assessment-assignments"),
        ("get", "/api/v1/account/assessment-assignments/{assignment_id}"),
        ("post", "/api/v1/account/assessment-assignments/{assignment_id}/attempt"),
        ("get", "/api/v1/account/assessment-attempts/{attempt_id}"),
        ("put", "/api/v1/account/assessment-attempts/{attempt_id}/draft"),
        ("post", "/api/v1/account/assessment-attempts/{attempt_id}/submit"),
        ("get", "/api/v1/account/assessment-attempts/{attempt_id}/result"),
    }
    serialized = str(app.openapi()).lower()
    for forbidden in ("refresh_token", "private_key", "credential_id", "numeric_value"):
        assert forbidden not in serialized
    item_schema = app.openapi()["components"]["schemas"]["AssessmentItemResponse"]
    assert {"weight", "passing_value"}.issubset(item_schema["properties"])
    list_parameters = {
        value["name"]
        for value in app.openapi()["paths"][
            "/api/v1/account/assessment-assignments"
        ]["get"]["parameters"]
    }
    assert list_parameters == {
        "company_id",
        "history_period",
        "date_from",
        "date_to",
    }


def test_draft_route_documents_success_and_revision_conflict(monkeypatch):
    _, _, app = make_client(monkeypatch)
    operation = app.openapi()["paths"][
        "/api/v1/account/assessment-attempts/{attempt_id}/draft"
    ]["put"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/AttemptDocumentResponse")
    assert operation["responses"]["409"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RevisionConflictResponse")
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["AttemptUiMetadataResponse"]["additionalProperties"] is False
    assert "section_order" in schemas["AttemptUiMetadataResponse"]["properties"]


def test_draft_request_accepts_only_typed_section_order(monkeypatch):
    attempt_id = uuid4()
    section_id = uuid4()
    captured = None

    class Service:
        def __init__(self, _session):
            pass

        async def replace_draft(self, command):
            nonlocal captured
            captured = command
            return attempt_document(attempt_id)

    monkeypatch.setattr(account_assessments, "AssessmentAttemptService", Service)
    http, _, _ = make_client(monkeypatch)
    response = http.put(
        f"/api/v1/account/assessment-attempts/{attempt_id}/draft",
        json={"expected_revision": 0, "answers": [], "section_order": [str(section_id)]},
    )
    assert response.status_code == 200
    assert captured.section_order == [section_id]
    invalid = http.put(
        f"/api/v1/account/assessment-attempts/{attempt_id}/draft",
        json={"expected_revision": 1, "answers": [], "section_order": ["not-a-uuid"]},
    )
    assert invalid.status_code == 422


def test_all_success_schemas_are_strict_and_typed(monkeypatch):
    _, _, app = make_client(monkeypatch)
    spec = app.openapi()
    expected = {
        (
            "get",
            "/api/v1/account/assessment-assignments",
        ): "AssessmentAssignmentSummaryResponse",
        (
            "get",
            "/api/v1/account/assessment-assignments/{assignment_id}",
        ): "AssessmentAssignmentDetailResponse",
        (
            "post",
            "/api/v1/account/assessment-assignments/{assignment_id}/attempt",
        ): "AttemptDocumentResponse",
        (
            "get",
            "/api/v1/account/assessment-attempts/{attempt_id}",
        ): "AttemptDocumentResponse",
        (
            "put",
            "/api/v1/account/assessment-attempts/{attempt_id}/draft",
        ): "AttemptDocumentResponse",
        ("post", "/api/v1/account/assessment-attempts/{attempt_id}/submit"): {
            "AssessmentCompletionV1Response",
            "AssessmentWeightedV1Response",
        },
        ("get", "/api/v1/account/assessment-attempts/{attempt_id}/result"): {
            "AssessmentCompletionV1Response",
            "AssessmentWeightedV1Response",
        },
    }
    operation_ids = []
    for (method, path), model in expected.items():
        operation = spec["paths"][path][method]
        operation_ids.append(operation["operationId"])
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        if isinstance(model, set):
            references = {value["$ref"].rsplit("/", 1)[-1] for value in schema["anyOf"]}
            assert references == model
        else:
            reference = (
                schema["items"]["$ref"]
                if path.endswith("assignments")
                else schema["$ref"]
            )
            assert reference.endswith(f"/{model}")
    assert len(operation_ids) == len(set(operation_ids)) == 7
    public_models = {
        name: schema
        for name, schema in spec["components"]["schemas"].items()
        if name.startswith("Assessment")
        or name
        in {
            "AttemptAnswerResponse",
            "AttemptDocumentResponse",
            "RevisionConflictDetail",
            "RevisionConflictResponse",
        }
    }
    assert public_models
    assert all(
        schema.get("additionalProperties") is False for schema in public_models.values()
    )
    serialized = str(public_models).lower()
    for forbidden in (
        "numeric_value",
        "is_correct",
        "recommendations",
        "is_disqualifying",
        "edit_revision",
        "account_id",
        "session_id",
        "device_id",
        "result_json",
        "refresh_token",
        "access_token",
        "credential",
        "digest",
        "private_key",
    ):
        assert forbidden not in serialized


def test_unknown_draft_fields_are_rejected_before_service(monkeypatch):
    http, session, _ = make_client(monkeypatch)
    response = http.put(
        f"/api/v1/account/assessment-attempts/{uuid4()}/draft",
        json={"expected_revision": 0, "answers": [], "status": "submitted"},
    )
    assert response.status_code == 422
    assert session.commits == session.rollbacks == 0


def test_mutation_is_no_store_and_never_sets_cookie(monkeypatch):
    attempt_id = uuid4()

    class Service:
        def __init__(self, _session):
            pass

        async def replace_draft(self, _command):
            return attempt_document(attempt_id)

    monkeypatch.setattr(account_assessments, "AssessmentAttemptService", Service)
    http, session, _ = make_client(monkeypatch)
    response = http.put(
        f"/api/v1/account/assessment-attempts/{attempt_id}/draft",
        json={"expected_revision": 0, "answers": []},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    assert session.commits == 1 and session.rollbacks == 0


def test_six_success_boundaries_validate_runtime_payloads(monkeypatch):
    assignment_id, attempt_id = uuid4(), uuid4()

    class Service:
        def __init__(self, _session):
            pass

        async def list_assignments(self, *_args, **_kwargs):
            return [assignment_summary(assignment_id)]

        async def assignment_detail(self, *_args):
            return assignment_detail(assignment_id)

        async def create_or_resume(self, *_args):
            return attempt_document(attempt_id)

        async def read_attempt(self, *_args):
            return attempt_document(attempt_id)

        async def submit(self, *_args):
            return completion_result()

        async def result(self, *_args):
            return completion_result()

    monkeypatch.setattr(account_assessments, "AssessmentAttemptService", Service)
    http, _, _ = make_client(monkeypatch)
    requests = [
        ("get", "/api/v1/account/assessment-assignments"),
        ("get", f"/api/v1/account/assessment-assignments/{assignment_id}"),
        ("post", f"/api/v1/account/assessment-assignments/{assignment_id}/attempt"),
        ("get", f"/api/v1/account/assessment-attempts/{attempt_id}"),
        ("post", f"/api/v1/account/assessment-attempts/{attempt_id}/submit"),
        ("get", f"/api/v1/account/assessment-attempts/{attempt_id}/result"),
    ]
    for method, path in requests:
        response = getattr(http, method)(path)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
    assert set(
        http.get(f"/api/v1/account/assessment-attempts/{attempt_id}/result").json()
    ) == {
        "scoring_algorithm",
        "submitted_at",
        "answered_count",
        "required_count",
        "total_count",
    }


def test_strict_response_models_reject_internal_fields():
    with pytest.raises(ValidationError):
        account_assessments.AssessmentCompletionV1Response.model_validate(
            {
                **completion_result(),
                "result_json": {"score": 100},
            }
        )
    with pytest.raises(ValidationError):
        account_assessments.AssessmentAssignmentDetailResponse.model_validate(
            {
                **assignment_detail(),
                "numeric_value": 10,
            }
        )
