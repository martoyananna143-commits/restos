"""Evaluation Types API router."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import get_current_employee, get_optional_current_user
from app.api.deps import get_evaluation_type_service
from app.api.schemas import (
    EvaluationTypeCreate,
    EvaluationTypeResponse,
)
from app.infra.database.models.employee.employee import Employee
from app.infra.database.models.user.user import User
from app.infra.database.repository.evaluation_type.dto import CreateEvaluationTypeDTO
from app.internal.usecases.evaluation_type_service import EvaluationTypeService

router = APIRouter(prefix="/evaluation-types", tags=["evaluation-types"])


@router.get("", response_model=List[EvaluationTypeResponse])
async def list_evaluation_types(
    organization_id: Optional[int] = Query(None, description="Filter by organization ID"),
    user: Optional[User] = Depends(get_optional_current_user),
    service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    """Get all evaluation types.
    
    Optional authentication - returns global types if not authenticated,
    or global + organization-specific types if authenticated.
    
    Args:
        organization_id: Optional organization ID to filter by.
        user: Optional authenticated user.
        service: EvaluationType service dependency.
        
    Returns:
        List of evaluation types.
    """
    # If organization_id provided but user not authenticated, return only global types
    if organization_id and not user:
        organization_id = None
    
    evaluation_types = await service.get_all(organization_id=organization_id)
    return evaluation_types


@router.get("/{evaluation_type_id}", response_model=EvaluationTypeResponse)
async def get_evaluation_type(
    evaluation_type_id: int,
    user: Optional[User] = Depends(get_optional_current_user),
    service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    """Get evaluation type by ID.
    
    Optional authentication - returns type if global or user has access.
    
    Args:
        evaluation_type_id: Evaluation type ID.
        user: Optional authenticated user.
        service: EvaluationType service dependency.
        
    Returns:
        Evaluation type details.
        
    Raises:
        HTTPException: If evaluation type not found.
    """
    evaluation_type = await service.get_by_id(evaluation_type_id)
    if not evaluation_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation type not found",
        )
    return evaluation_type


@router.post("", response_model=EvaluationTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation_type(
    data: EvaluationTypeCreate,
    service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    """Create a new evaluation type.
    
    Args:
        data: Evaluation type creation data.
        service: EvaluationType service dependency.
        
    Returns:
        Created evaluation type.
    """
    dto = CreateEvaluationTypeDTO(
        organization_id=data.organization_id,
        name=data.name,
        code=data.code,
        description=data.description,
    )
    evaluation_type = await service.create(dto)
    return evaluation_type
