"""HTTP boundary tests for the authenticated assessment API."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_invitation_auth, assessment_templates
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_draft_service import (
    AssessmentDraftRevisionConflict,
)
from app.internal.services.assessment_template_service import (
    AssessmentTemplateCodeConflict,
    AssessmentTemplatePublicationInvalid,
)


NOW = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
ACCOUNT_ID = uuid4()
COMPANY_ID = uuid4()
TEMPLATE_ID = uuid4()
VERSION_ID = uuid4()


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def principal():
    return CurrentAccountPrincipal(
        ACCOUNT_ID, uuid4(), uuid4(), 1, NOW
    )


def client(monkeypatch, *, allowed=True, session=None):
    session = session or FakeSession()

    async def session_override():
        yield session

    async def principal_override():
        return principal()

    class Decisions:
        def __init__(self, _session):
            pass

        async def can_in_company(
            self, account_id, company_id, permission, now=None
        ):
            assert account_id == ACCOUNT_ID
            assert company_id == COMPANY_ID
            assert permission in {
                "assessment.template.read",
                "assessment.template.manage",
            }
            return allowed

    monkeypatch.setattr(
        assessment_templates, "AccessDecisionService", Decisions
    )
    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(assessment_templates.router)
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    app.dependency_overrides[
        get_current_account_principal
    ] = principal_override

    @app.get("/legacy/{value}")
    async def legacy(value: int):
        return {"value": value}

    return TestClient(app, raise_server_exceptions=False), session


def document():
    return {
        "template": {
            "id": TEMPLATE_ID,
            "scope": "library",
            "code": "service",
            "name": "Service",
        },
        "version": {
            "version_id": VERSION_ID,
            "version": 1,
            "status": "published",
            "edit_revision": 1,
        },
        "methodology": {
            "id": uuid4(),
            "title": "Method",
            "body": "Read only",
            "version": 1,
        },
        "sections": [],
    }


def draft_payload(items=1):
    return {
        "expected_edit_revision": 1,
        "template_name": "Local template",
        "sections": [
            {
                "code": "section",
                "title": "Section",
                "section_kind": "section",
                "sort_order": 0,
                "items": [
                    {
                        "code": f"item-{index}",
                        "prompt": "Question",
                        "response_type": "boolean",
                        "sort_order": index,
                        "evidence_mode": "none",
                        "criticality": "normal",
                        "config": {"depth": {"safe": True}},
                    }
                    for index in range(items)
                ],
            }
        ],
    }


def test_authentication_is_required_without_override():
    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(assessment_templates.router)
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.get("/api/v1/assessment-library")
    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "authentication_required"}
    }
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "private, no-store"


def test_library_list_filters_and_is_no_store(monkeypatch):
    captured = {}

    class Catalog:
        def __init__(self, _session):
            pass

        async def list_library_templates(self, request):
            captured["request"] = request
            return [{"template_id": TEMPLATE_ID, "version_id": VERSION_ID}]

    monkeypatch.setattr(assessment_templates, "AssessmentCatalogService", Catalog)
    http, session = client(monkeypatch)
    response = http.get(
        "/api/v1/assessment-library",
        params={
            "activity_type": "evaluation",
            "query": r"100%_safe",
            "limit": 10,
            "offset": 2,
        },
    )
    assert response.status_code == 200
    assert captured["request"].query == r"100%_safe"
    assert captured["request"].limit == 10
    assert captured["request"].offset == 2
    assert session.commits == session.rollbacks == 0
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/assessment-library/{TEMPLATE_ID}",
        f"/api/v1/assessment-library/{TEMPLATE_ID}/versions/{VERSION_ID}",
    ],
)
def test_library_detail_returns_methodology_and_tree(monkeypatch, path):
    class Catalog:
        def __init__(self, _session):
            pass

        async def get_library_template(self, *_args):
            return document()

    monkeypatch.setattr(assessment_templates, "AssessmentCatalogService", Catalog)
    http, _ = client(monkeypatch)
    response = http.get(path)
    assert response.status_code == 200
    assert response.json()["methodology"]["body"] == "Read only"
    assert response.json()["sections"] == []


def test_company_permission_denied(monkeypatch):
    http, session = client(monkeypatch, allowed=False)
    response = http.get(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates"
    )
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "permission_denied"}}
    assert session.commits == session.rollbacks == 0


def test_company_list_uses_read_permission(monkeypatch):
    class Catalog:
        def __init__(self, _session):
            pass

        async def list_company_templates(self, company_id):
            assert company_id == COMPANY_ID
            return []

    monkeypatch.setattr(assessment_templates, "AssessmentCatalogService", Catalog)
    http, session = client(monkeypatch)
    response = http.get(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates"
    )
    assert response.status_code == 200
    assert response.json() == []
    assert session.commits == session.rollbacks == 0


def test_adopt_commits_and_returns_counts(monkeypatch):
    class Templates:
        def __init__(self, _session):
            pass

        async def adopt_library_template(self, request):
            assert request.company_id == COMPANY_ID
            return SimpleNamespace(
                company_template_id=TEMPLATE_ID,
                draft_version_id=VERSION_ID,
                source_library_version_id=request.source_library_version_id,
                methodology_id=uuid4(),
                section_count=1,
                item_count=240,
                option_count=0,
            )

        async def publish_template_version(self, request):
            return SimpleNamespace(template_id=request.template_id)

    monkeypatch.setattr(assessment_templates, "AssessmentTemplateService", Templates)
    http, session = client(monkeypatch)
    source_id = uuid4()
    response = http.post(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/adopt",
        json={
            "source_library_version_id": str(source_id),
            "company_template_code": "local-service",
        },
    )
    assert response.status_code == 201
    assert response.json()["item_count"] == 240
    assert session.commits == 1 and session.rollbacks == 0


def test_duplicate_adopt_rolls_back_and_is_409(monkeypatch):
    class Templates:
        def __init__(self, _session):
            pass

        async def adopt_library_template(self, _request):
            raise AssessmentTemplateCodeConflict("private details")

    monkeypatch.setattr(assessment_templates, "AssessmentTemplateService", Templates)
    http, session = client(monkeypatch)
    response = http.post(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/adopt",
        json={
            "source_library_version_id": str(uuid4()),
            "company_template_code": "duplicate",
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "assessment_code_conflict"}
    }
    assert "private details" not in response.text
    assert session.rollbacks == 1


def test_save_240_items_commits_and_returns_document(monkeypatch):
    class Drafts:
        def __init__(self, _session):
            pass

        async def save_draft_document(self, request):
            assert len(request.sections[0].items) == 240
            return SimpleNamespace(edit_revision=2)

    class Catalog:
        def __init__(self, _session):
            pass

        async def get_company_template_version(self, *_args):
            result = document()
            result["version"]["edit_revision"] = 2
            return result

    monkeypatch.setattr(assessment_templates, "AssessmentDraftService", Drafts)
    monkeypatch.setattr(assessment_templates, "AssessmentCatalogService", Catalog)
    http, session = client(monkeypatch)
    response = http.put(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/"
        f"{TEMPLATE_ID}/versions/{VERSION_ID}/draft",
        json=draft_payload(240),
    )
    assert response.status_code == 200
    assert response.json()["version"]["edit_revision"] == 2
    assert session.commits == 1 and session.rollbacks == 0


def test_revision_conflict_rolls_back(monkeypatch):
    class Drafts:
        def __init__(self, _session):
            pass

        async def save_draft_document(self, _request):
            raise AssessmentDraftRevisionConflict("private revision")

    monkeypatch.setattr(assessment_templates, "AssessmentDraftService", Drafts)
    http, session = client(monkeypatch)
    response = http.put(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/"
        f"{TEMPLATE_ID}/versions/{VERSION_ID}/draft",
        json=draft_payload(),
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "assessment_revision_conflict"}
    }
    assert session.rollbacks == 1


def test_publish_invalid_is_safe_400(monkeypatch):
    class Templates:
        def __init__(self, _session):
            pass

        async def publish_template_version(self, _request):
            raise AssessmentTemplatePublicationInvalid("methodology body")

    monkeypatch.setattr(assessment_templates, "AssessmentTemplateService", Templates)
    http, session = client(monkeypatch)
    response = http.post(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/"
        f"{TEMPLATE_ID}/versions/{VERSION_ID}/publish"
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "assessment_publication_invalid"}
    }
    assert "methodology body" not in response.text
    assert session.rollbacks == 1


@pytest.mark.parametrize(
    "extra_field",
    [
        "methodology_id",
        "source_library_version_id",
        "company_id",
        "scope",
        "activity_type",
        "version",
        "status",
        "published_at",
        "edit_revision",
    ],
)
def test_draft_protected_fields_are_422(monkeypatch, extra_field):
    http, session = client(monkeypatch)
    payload = draft_payload()
    payload[extra_field] = "forbidden-secret-input"
    response = http.put(
        f"/api/v1/companies/{COMPANY_ID}/assessment-templates/"
        f"{TEMPLATE_ID}/versions/{VERSION_ID}/draft",
        json=payload,
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_assessment_request"}
    }
    assert "forbidden-secret-input" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert session.commits == session.rollbacks == 0


def test_unexpected_error_is_safe_500(monkeypatch):
    class Catalog:
        def __init__(self, _session):
            pass

        async def list_library_templates(self, _request):
            raise RuntimeError("private SQL and methodology body")

    monkeypatch.setattr(assessment_templates, "AssessmentCatalogService", Catalog)
    http, _ = client(monkeypatch)
    response = http.get("/api/v1/assessment-library")
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "private SQL" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_legacy_validation_is_unchanged(monkeypatch):
    http, _ = client(monkeypatch)
    response = http.get("/legacy/not-an-int")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert "cache-control" not in response.headers


def test_openapi_has_routes_security_and_no_protected_draft_fields(monkeypatch):
    http, _ = client(monkeypatch)
    schema = http.app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/assessment-library",
        "/api/v1/assessment-library/{template_id}",
        "/api/v1/assessment-library/{template_id}/versions/{version_id}",
        "/api/v1/companies/{company_id}/assessment-templates",
        "/api/v1/companies/{company_id}/assessment-templates/adopt",
        "/api/v1/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}",
        "/api/v1/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/draft",
        "/api/v1/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/publish",
        "/api/v1/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/next-draft",
    }
    assert expected <= set(paths)
    request_schema = schema["components"]["schemas"]["SaveAssessmentDraftRequest"]
    properties = request_schema["properties"]
    assert "expected_edit_revision" in properties
    for field in (
        "methodology_id", "source_library_version_id", "company_id",
        "scope", "activity_type", "version", "status", "published_at",
        "edit_revision",
    ):
        assert field not in properties
    serialized = str(schema).lower()
    assert "account_auth_access_token_key" not in serialized
    assert "refresh_token" not in serialized
