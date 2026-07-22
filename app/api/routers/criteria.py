"""Criteria API router."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user, verify_admin_access, verify_organization_access
from app.api.deps import get_criterion_service, get_employee_service, get_organization_service
from app.api.schemas import (
    CriterionCreate,
    CriterionResponse,
    CriterionUpdate,
)
from app.infra.database.models.user.user import User
from app.infra.database.repository.criterion.dto import (
    CreateCriterionDTO,
    UpdateCriterionDTO,
)
from app.internal.services.criterion_service import CriterionService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService

router = APIRouter(prefix="/criteria", tags=["criteria"])


@router.get("", response_model=List[CriterionResponse])
async def list_criteria(
    organization_id: int,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    service: CriterionService = Depends(get_criterion_service),
):
    """Get criteria list for organization.
    
    Requires employee access to the organization.
    
    Args:
        organization_id: Organization ID (query parameter).
        user: Authenticated user.
        employee_service: Employee service dependency.
        service: Criterion service dependency.
        
    Returns:
        List of criteria.
        
    Raises:
        HTTPException: If access denied.
    """
    # Verify user has access to this organization
    await verify_organization_access(user, organization_id, employee_service)
    
    criteria = await service.get_by_organization_id(organization_id)
    return criteria


@router.get("/{criterion_id}", response_model=CriterionResponse)
async def get_criterion(
    criterion_id: int,
    employee: Employee = Depends(get_current_employee),
    service: CriterionService = Depends(get_criterion_service),
):
    """Get criterion by ID.
    
    Requires employee access to the criterion's organization.
    
    Args:
        criterion_id: Criterion ID.
        employee: Authenticated employee in organization.
        service: Criterion service dependency.
        
    Returns:
        Criterion details.
        
    Raises:
        HTTPException: If criterion not found or access denied.
    """
    criterion = await service.get_by_id(criterion_id)
    if not criterion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion not found",
        )
    
    # Verify employee has access to criterion's organization
    if criterion.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this criterion",
        )
    
    return criterion


@router.post("", response_model=CriterionResponse, status_code=status.HTTP_201_CREATED)
async def create_criterion(
    data: CriterionCreate,
    employee: Employee = Depends(require_admin),
    criterion_service: CriterionService = Depends(get_criterion_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Create a new criterion.
    
    Requires administrator access in the organization.
    
    Args:
        data: Criterion creation data.
        employee: Authenticated admin employee.
        criterion_service: Criterion service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Created criterion.
        
    Raises:
        HTTPException: If organization not found or access denied.
    """
    # Verify admin has access to this organization
    if employee.organization_id != data.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    # Verify organization exists
    organization = await organization_service.get_by_id(data.organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    dto = CreateCriterionDTO(
        organization_id=data.organization_id,
        name=data.name,
        code=data.code,
        description=data.description,
        value_type=data.value_type,
        sort_order=data.sort_order,
    )
    criterion = await criterion_service.create(dto)
    return criterion


@router.put("/{criterion_id}", response_model=CriterionResponse)
async def update_criterion(
    criterion_id: int,
    data: CriterionUpdate,
    employee: Employee = Depends(require_admin),
    service: CriterionService = Depends(get_criterion_service),
):
    """Update criterion.
    
    Requires administrator access in the criterion's organization.
    
    Args:
        criterion_id: Criterion ID.
        data: Criterion update data.
        employee: Authenticated admin employee.
        service: Criterion service dependency.
        
    Returns:
        Updated criterion.
        
    Raises:
        HTTPException: If criterion not found or access denied.
    """
    # Get existing criterion
    existing = await service.get_by_id(criterion_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion not found",
        )
    
    # Verify admin has access to criterion's organization
    if existing.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this criterion",
        )
    
    dto = UpdateCriterionDTO(
        name=data.name,
        code=data.code,
        description=data.description,
        value_type=data.value_type,
    )
    criterion = await service.update(criterion_id, dto)
    if not criterion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criterion not found",
        )
    return criterion
