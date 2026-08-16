"""Strict OpenAPI contracts for restaurant metrics and product measurements."""

from fastapi import FastAPI
from pydantic import ValidationError
import pytest

from app.api.routers import account_product_measurements, account_restaurant_metrics
from app.api.routers.account_invitation_auth import configure_account_auth_http_security


def application() -> FastAPI:
    app = FastAPI()
    configure_account_auth_http_security(app)
    app.include_router(account_restaurant_metrics.router)
    app.include_router(account_product_measurements.router)
    return app


def test_metric_and_measurement_openapi_has_exact_seven_typed_operations() -> None:
    spec = application().openapi()
    operations = {
        (method, path)
        for path, value in spec["paths"].items()
        for method in value
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert operations == {
        ("get", "/api/v1/account/companies/{company_id}/restaurant-metrics"),
        (
            "get",
            "/api/v1/account/companies/{company_id}/restaurant-metrics/{metric_code}/sources",
        ),
        (
            "get",
            "/api/v1/account/companies/{company_id}/restaurant-metrics/low-indicators",
        ),
        (
            "get",
            "/api/v1/account/companies/{company_id}/restaurant-metrics/options",
        ),
        ("post", "/api/v1/account/companies/{company_id}/product-measurements"),
        (
            "put",
            "/api/v1/account/companies/{company_id}/product-measurements/{measurement_id}",
        ),
        (
            "post",
            "/api/v1/account/companies/{company_id}/product-measurements/{measurement_id}/complete",
        ),
    }
    for method, path in operations:
        response = spec["paths"][path][method]["responses"]
        status = "201" if path.endswith("product-measurements") else "200"
        schema = response[status]["content"]["application/json"]["schema"]
        assert schema.get("$ref") or schema.get("items", {}).get("$ref")


def test_new_public_models_are_strict_and_exclude_private_evidence() -> None:
    schemas = application().openapi()["components"]["schemas"]
    names = {
        "RestaurantMetricDashboardResponse",
        "RestaurantMetricResponse",
        "MetricSourceComponentResponse",
        "MetricSourceDrilldownResponse",
        "MetricCriterionContributionResponse",
        "LowIndicatorItemResponse",
        "LowIndicatorRankingResponse",
        "MetricTemplateOptionResponse",
        "ProductMeasurementResponse",
        "ProductMeasurementResult",
        "ProductMetricComponent",
        "ProductPositionResult",
        "ProductItem-Input",
        "ProductItem-Output",
        "CreateProductMeasurement",
        "ReplaceProductMeasurement",
        "CompleteProductMeasurement",
        "ProductMeasurementError",
        "ProductMeasurementErrorDetail",
    }
    assert names.issubset(schemas)
    assert all(schemas[name].get("additionalProperties") is False for name in names)
    serialized = str({name: schemas[name] for name in names}).lower()
    for forbidden in (
        "phone",
        "employee_name",
        "account_id",
        "answer",
        "comment_text",
        "token",
        "cookie",
        "credential",
    ):
        assert forbidden not in serialized


def test_dashboard_contract_exposes_bounded_section_filter_without_composite() -> None:
    spec = application().openapi()
    dashboard = spec["paths"][
        "/api/v1/account/companies/{company_id}/restaurant-metrics"
    ]["get"]
    section = next(
        value for value in dashboard["parameters"] if value["name"] == "section_code"
    )
    string_schema = next(
        value for value in section["schema"]["anyOf"] if value.get("type") == "string"
    )
    assert string_schema["maxLength"] == 100
    assert string_schema["pattern"] == "^[a-z0-9][a-z0-9._-]*$"
    response = (
        account_restaurant_metrics.RestaurantMetricDashboardResponse.model_validate(
            {
                "company_id": "00000000-0000-0000-0000-000000000001",
                "venue_id": None,
                "source_type": "walkthrough",
                "section_code": "service-management",
                "from_at": "2026-08-01T00:00:00Z",
                "to_at": "2026-08-11T00:00:00Z",
                "timezone": "Europe/Moscow",
                "comparison_from_at": None,
                "comparison_to_at": None,
                "aggregation_status": "components_only",
                "metrics": [],
            }
        )
    )
    assert response.section_code == "service-management"


def test_dashboard_documents_comparison_and_ranking_contracts() -> None:
    spec = application().openapi()
    dashboard = spec["components"]["schemas"]["MetricSourceComponentResponse"]
    assert {
        "scoring_algorithm",
        "scoring_version",
        "comparison_status",
        "delta",
        "delta_unit",
    }.issubset(dashboard["properties"])
    ranking = account_restaurant_metrics.LowIndicatorRankingResponse.model_validate(
        {
            "template_version_id": "00000000-0000-0000-0000-000000000001",
            "scoring_algorithm": "weighted_v1",
            "scoring_version": 1,
            "from_at": "2026-08-01T00:00:00Z",
            "to_at": "2026-08-14T00:00:00Z",
            "minimum_observations": 3,
            "maximum_items": 10,
            "observation_count": 3,
            "status": "available",
            "items": [
                {
                    "rank": 1,
                    "item_code": "service-speed",
                    "label": "Скорость обслуживания",
                    "score_percent": "50.0000",
                    "sample_count": 3,
                    "coverage": "1.000000",
                    "critical_failure_count": 0,
                    "stop_factor_count": 0,
                }
            ],
        }
    )
    assert ranking.items[0].rank == 1


def test_product_item_rejects_unknown_fields_and_out_of_range_scores() -> None:
    value = {
        "position_type": "dish",
        "position_name": "Тестовая позиция",
        "taste_score": "3",
        "appearance_score": "2",
        "output_score": "3",
        "ticket_time_score": "2",
        "planned_quantity": "250",
        "actual_quantity": "245",
        "quantity_unit": "g",
        "planned_ticket_seconds": 600,
        "actual_ticket_seconds": 590,
        "comment": None,
    }
    assert account_product_measurements.ProductItem.model_validate(value)
    assert account_product_measurements.CreateProductMeasurement.model_validate(
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "venue_id": "00000000-0000-0000-0000-000000000002",
        }
    )
    with pytest.raises(ValidationError):
        account_product_measurements.ProductItem.model_validate(
            {**value, "taste_score": "4"}
        )
    with pytest.raises(ValidationError):
        account_product_measurements.ProductItem.model_validate(
            {**value, "raw_provider_payload": {}}
        )
