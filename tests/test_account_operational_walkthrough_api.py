"""Strict Account operational walkthrough HTTP/OpenAPI contract tests."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_operational_walkthroughs
from app.api.routers.account_invitation_auth import (
    configure_account_auth_http_security,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


class FakeSession:
    pass


def make_client():
    async def principal():
        return CurrentAccountPrincipal(uuid4(), uuid4(), uuid4(), 1, NOW)

    async def database():
        yield FakeSession()

    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_operational_walkthroughs.router)
    app.dependency_overrides[get_current_account_principal] = principal
    app.dependency_overrides[get_account_auth_session] = database
    return TestClient(app, raise_server_exceptions=False), app


def test_openapi_has_exact_two_strict_typed_operations():
    _, app = make_client()
    prefix = "/api/v1/account/companies/{company_id}/operational-walkthroughs"
    operations = {
        (method, path)
        for path, value in app.openapi()["paths"].items()
        for method in value
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert operations == {("get", f"{prefix}/templates"), ("post", prefix)}
    schemas = app.openapi()["components"]["schemas"]
    for name in (
        "OperationalWalkthroughTemplateResponse",
        "StartOperationalWalkthroughRequest",
        "OperationalWalkthroughError",
        "OperationalWalkthroughErrorDetail",
    ):
        assert schemas[name]["additionalProperties"] is False
    success = app.openapi()["paths"][prefix]["post"]["responses"]["201"]
    assert success["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AttemptDocumentResponse"
    )


def test_start_rejects_unknown_or_missing_venue_before_service():
    http, _ = make_client()
    route = f"/api/v1/account/companies/{uuid4()}/operational-walkthroughs"
    unknown = http.post(
        route,
        json={
            "venue_id": str(uuid4()),
            "template_version_id": str(uuid4()),
            "employee_profile_id": str(uuid4()),
        },
    )
    missing = http.post(route, json={"template_version_id": str(uuid4())})
    assert unknown.status_code == missing.status_code == 422


def test_template_projection_contains_no_employee_or_private_fields():
    model = account_operational_walkthroughs.OperationalWalkthroughTemplateResponse
    value = model.model_validate(
        {
            "template_id": uuid4(),
            "template_version_id": uuid4(),
            "name": "Производственный обход",
            "version": 1,
            "section_count": 11,
            "item_count": 199,
            "scoring_algorithm": "weighted_v1",
            "scoring_ready": True,
        }
    )
    serialized = value.model_dump_json().lower()
    for forbidden in ("employee", "phone", "answer", "comment", "token", "credential"):
        assert forbidden not in serialized
