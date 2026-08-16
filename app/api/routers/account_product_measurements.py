"""Strict Account-scoped repeatable taste/speed measurement boundary."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_product_measurement_service import (
    AssessmentProductMeasurementService,
    ProductItemInput,
    ProductMeasurementConflict,
    ProductMeasurementInvalid,
    ProductMeasurementNotFound,
    ProductMeasurementPermissionDenied,
)


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/product-measurements",
    tags=["account-product-measurements"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductMeasurementErrorDetail(StrictModel):
    code: Literal[
        "permission_denied",
        "product_measurement_not_found",
        "product_measurement_conflict",
        "invalid_product_measurement",
    ]


class ProductMeasurementError(StrictModel):
    detail: ProductMeasurementErrorDetail


class ProductItem(StrictModel):
    position_type: Literal["dish", "drink"]
    position_name: str = Field(min_length=1, max_length=255)
    taste_score: Decimal = Field(ge=0, le=3)
    appearance_score: Decimal = Field(ge=0, le=3)
    output_score: Decimal = Field(ge=0, le=3)
    ticket_time_score: Decimal = Field(ge=0, le=3)
    planned_quantity: Decimal = Field(ge=0)
    actual_quantity: Decimal = Field(ge=0)
    quantity_unit: Literal["g", "ml"]
    planned_ticket_seconds: int = Field(ge=0, le=86_400)
    actual_ticket_seconds: int = Field(ge=0, le=86_400)
    comment: str | None = Field(default=None, max_length=10_000)


class CreateProductMeasurement(StrictModel):
    request_id: UUID
    venue_id: UUID


class ReplaceProductMeasurement(StrictModel):
    expected_revision: int = Field(ge=0)
    items: list[ProductItem] = Field(max_length=200)


class CompleteProductMeasurement(StrictModel):
    expected_revision: int = Field(ge=0)


class ProductMetricComponent(StrictModel):
    numerator: str
    denominator: str
    score_percent: str
    coverage: str


class ProductPositionResult(StrictModel):
    position_index: int = Field(ge=0)
    position_type: Literal["dish", "drink"]
    taste: ProductMetricComponent
    speed: ProductMetricComponent
    overall: ProductMetricComponent


class ProductMeasurementResult(StrictModel):
    scoring_algorithm: Literal["product_measurement_v1"]
    scoring_version: Literal[1]
    item_count: int = Field(ge=1)
    taste: ProductMetricComponent
    speed: ProductMetricComponent
    overall: ProductMetricComponent
    items: list[ProductPositionResult]


class ProductMeasurementResponse(StrictModel):
    id: UUID
    company_id: UUID
    venue_id: UUID
    status: Literal["draft", "completed"]
    revision: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime | None
    result: ProductMeasurementResult | None
    items: list[ProductItem]


ERRORS = {
    401: {"model": PublicError},
    403: {"model": ProductMeasurementError},
    404: {"model": ProductMeasurementError},
    409: {"model": ProductMeasurementError},
    422: {"model": ProductMeasurementError},
}


def _item(value: ProductItem) -> ProductItemInput:
    return ProductItemInput(**value.model_dump())


def _error(problem: Exception) -> HTTPException:
    if isinstance(problem, ProductMeasurementPermissionDenied):
        code, http = "permission_denied", status.HTTP_403_FORBIDDEN
    elif isinstance(problem, ProductMeasurementNotFound):
        code, http = "product_measurement_not_found", status.HTTP_404_NOT_FOUND
    elif isinstance(problem, ProductMeasurementConflict):
        code, http = "product_measurement_conflict", status.HTTP_409_CONFLICT
    elif isinstance(problem, ProductMeasurementInvalid):
        code, http = "invalid_product_measurement", status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        raise problem
    return HTTPException(
        http, detail={"code": code}, headers={"Cache-Control": NO_STORE}
    )


@router.post(
    "",
    response_model=ProductMeasurementResponse,
    status_code=201,
    responses=ERRORS,
)
async def create_product_measurement(
    company_id: UUID,
    request: CreateProductMeasurement,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        value = await AssessmentProductMeasurementService(session).create(
            principal.account_id,
            company_id,
            request.request_id,
            request.venue_id,
            datetime.now(timezone.utc),
        )
        await session.commit()
        return value
    except Exception as problem:
        await session.rollback()
        raise _error(problem) from problem


@router.put(
    "/{measurement_id}",
    response_model=ProductMeasurementResponse,
    responses=ERRORS,
)
async def replace_product_measurement(
    company_id: UUID,
    measurement_id: UUID,
    request: ReplaceProductMeasurement,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        value = await AssessmentProductMeasurementService(session).replace(
            principal.account_id,
            company_id,
            measurement_id,
            request.expected_revision,
            [_item(value) for value in request.items],
            datetime.now(timezone.utc),
        )
        await session.commit()
        return value
    except Exception as problem:
        await session.rollback()
        raise _error(problem) from problem


@router.post(
    "/{measurement_id}/complete",
    response_model=ProductMeasurementResponse,
    responses=ERRORS,
)
async def complete_product_measurement(
    company_id: UUID,
    measurement_id: UUID,
    request: CompleteProductMeasurement,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        value = await AssessmentProductMeasurementService(session).complete(
            principal.account_id,
            company_id,
            measurement_id,
            request.expected_revision,
            datetime.now(timezone.utc),
        )
        await session.commit()
        return value
    except Exception as problem:
        await session.rollback()
        raise _error(problem) from problem
