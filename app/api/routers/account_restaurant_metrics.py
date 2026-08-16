"""Strict Account-scoped restaurant metric dashboard boundary."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import (
    CurrentAccountPrincipal,
)
from app.internal.services.assessment_metric_dashboard_service import (
    AssessmentMetricDashboardInvalid,
    AssessmentMetricDashboardPermissionDenied,
    AssessmentMetricDashboardService,
)


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/restaurant-metrics",
    tags=["account-restaurant-metrics"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricDashboardErrorDetail(StrictModel):
    code: Literal["permission_denied", "invalid_metric_query"]


class MetricDashboardError(StrictModel):
    detail: MetricDashboardErrorDetail


class MetricSourceComponentResponse(StrictModel):
    source_type: Literal[
        "evaluation",
        "measurement",
        "walkthrough",
        "checklist",
        "test",
        "survey",
        "attestation",
    ]
    scoring_algorithm: Literal["weighted_v1", "product_measurement_v1"]
    scoring_version: Literal[1]
    score_percent: str
    coverage: str
    observation_count: int = Field(ge=1)
    critical_failure_count: int = Field(ge=0)
    stop_factor_count: int = Field(ge=0)
    latest_at: datetime
    comparison_status: Literal[
        "not_requested", "no_previous_data", "not_comparable", "comparable"
    ]
    delta: str | None
    delta_unit: Literal["percentage_points"] | None


class RestaurantMetricResponse(StrictModel):
    code: Literal[
        "taste",
        "speed",
        "order",
        "service",
        "people",
        "space",
        "economics",
        "food_safety",
    ]
    title: str
    composite_score_percent: None = None
    target_score_percent: None = None
    overdue_action_count: None = None
    status: Literal["no_data", "components_available"]
    components: list[MetricSourceComponentResponse]


class RestaurantMetricDashboardResponse(StrictModel):
    company_id: UUID
    venue_id: UUID | None
    source_type: (
        Literal[
            "evaluation",
            "measurement",
            "walkthrough",
            "checklist",
            "test",
            "survey",
            "attestation",
        ]
        | None
    )
    section_code: str | None
    from_at: datetime | None
    to_at: datetime
    timezone: str
    comparison_from_at: datetime | None
    comparison_to_at: datetime | None
    aggregation_status: Literal["components_only"]
    metrics: list[RestaurantMetricResponse]


class MetricCriterionContributionResponse(StrictModel):
    item_id: UUID | None = None
    section_id: UUID | None = None
    section_code: str | None = None
    item_code: str | None = None
    prompt: str | None = None
    position_index: int | None = Field(default=None, ge=0)
    position_type: Literal["dish", "drink"] | None = None
    normalized: str | None = None
    source_normalized: str | None = None
    weight: str | None = None
    critical_failure: bool | None = None
    stop_factor_failure: bool | None = None


class MetricSourceDrilldownResponse(StrictModel):
    observation_id: UUID
    attempt_id: UUID | None
    product_measurement_id: UUID | None
    source_type: Literal[
        "evaluation",
        "measurement",
        "walkthrough",
        "checklist",
        "test",
        "survey",
        "attestation",
    ]
    scoring_algorithm: str
    scoring_version: int = Field(ge=1)
    score_percent: str
    coverage: str
    critical_failure_count: int = Field(ge=0)
    stop_factor_count: int = Field(ge=0)
    observed_at: datetime
    items: list[MetricCriterionContributionResponse]


class LowIndicatorItemResponse(StrictModel):
    rank: int = Field(ge=1, le=10)
    item_code: str
    label: str
    score_percent: str
    sample_count: int = Field(ge=3)
    coverage: str
    critical_failure_count: int = Field(ge=0)
    stop_factor_count: int = Field(ge=0)


class LowIndicatorRankingResponse(StrictModel):
    template_version_id: UUID
    scoring_algorithm: Literal["weighted_v1"]
    scoring_version: Literal[1]
    from_at: datetime
    to_at: datetime
    minimum_observations: Literal[3]
    maximum_items: Literal[10]
    observation_count: int = Field(ge=0)
    status: Literal["available", "insufficient_data"]
    items: list[LowIndicatorItemResponse] = Field(max_length=10)


class MetricTemplateOptionResponse(StrictModel):
    template_version_id: UUID
    name: str
    activity_type: Literal[
        "evaluation",
        "measurement",
        "walkthrough",
        "checklist",
        "test",
        "survey",
        "attestation",
    ]
    completed_observation_count: int = Field(ge=1)


ERRORS = {
    401: {"model": PublicError},
    403: {"model": MetricDashboardError},
    422: {"model": MetricDashboardError},
}


@router.get(
    "",
    response_model=RestaurantMetricDashboardResponse,
    responses=ERRORS,
)
async def restaurant_metric_dashboard(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    venue_id: UUID | None = None,
    source_type: (
        Literal[
            "evaluation",
            "measurement",
            "walkthrough",
            "checklist",
            "test",
            "survey",
            "attestation",
        ]
        | None
    ) = None,
    section_code: Annotated[
        str | None,
        Query(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
    ] = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
    period: Literal["today"] | None = None,
    compare_previous: bool = False,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentMetricDashboardService(session).dashboard(
            principal.account_id,
            company_id,
            datetime.now(timezone.utc),
            venue_id=venue_id,
            source_type=source_type,
            section_code=section_code,
            from_at=from_at,
            to_at=to_at,
            period=period,
            compare_previous=compare_previous,
        )
    except AssessmentMetricDashboardPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied"},
            headers={"Cache-Control": NO_STORE},
        ) from error
    except AssessmentMetricDashboardInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_metric_query"},
            headers={"Cache-Control": NO_STORE},
        ) from error


@router.get(
    "/options",
    response_model=list[MetricTemplateOptionResponse],
    responses=ERRORS,
)
async def metric_template_options(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    venue_id: UUID | None = None,
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentMetricDashboardService(session).template_options(
            principal.account_id,
            company_id,
            datetime.now(timezone.utc),
            venue_id=venue_id,
        )
    except AssessmentMetricDashboardPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied"},
            headers={"Cache-Control": NO_STORE},
        ) from error


@router.get(
    "/low-indicators",
    response_model=LowIndicatorRankingResponse,
    responses=ERRORS,
)
async def low_indicator_ranking(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    template_version_id: UUID,
    venue_id: UUID | None = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentMetricDashboardService(session).low_indicators(
            principal.account_id,
            company_id,
            template_version_id,
            datetime.now(timezone.utc),
            venue_id=venue_id,
            from_at=from_at,
            to_at=to_at,
        )
    except AssessmentMetricDashboardPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied"},
            headers={"Cache-Control": NO_STORE},
        ) from error
    except AssessmentMetricDashboardInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_metric_query"},
            headers={"Cache-Control": NO_STORE},
        ) from error


@router.get(
    "/{metric_code}/sources",
    response_model=list[MetricSourceDrilldownResponse],
    responses=ERRORS,
)
async def restaurant_metric_sources(
    company_id: UUID,
    metric_code: Literal[
        "taste",
        "speed",
        "order",
        "service",
        "people",
        "space",
        "economics",
        "food_safety",
    ],
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    venue_id: UUID | None = None,
    source_type: (
        Literal[
            "evaluation",
            "measurement",
            "walkthrough",
            "checklist",
            "test",
            "survey",
            "attestation",
        ]
        | None
    ) = None,
    section_code: Annotated[
        str | None,
        Query(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentMetricDashboardService(session).sources(
            principal.account_id,
            company_id,
            metric_code,
            datetime.now(timezone.utc),
            venue_id=venue_id,
            source_type=source_type,
            section_code=section_code,
            limit=limit,
        )
    except AssessmentMetricDashboardPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied"},
            headers={"Cache-Control": NO_STORE},
        ) from error
