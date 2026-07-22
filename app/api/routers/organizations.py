"""Organizations API router."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user, verify_admin_access, verify_organization_access
from app.api.deps import get_employee_service, get_organization_service
from app.api.schemas import (
    EmployeeResponse,
    MessageResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.infra.database.models.user.user import User
from app.infra.database.repository.organization.dto import (
    CreateOrganizationDTO,
    UpdateOrganizationDTO,
)
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
):
    """Get all organizations for authenticated user.
    
    Args:
        user: Authenticated user.
        service: Organization service dependency.
        
    Returns:
        List of organizations.
    """
    organizations = await service.get_all_by_user_telegram_id(user.telegram_id)
    return organizations


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: int,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    service: OrganizationService = Depends(get_organization_service),
):
    """Get organization by ID.
    
    Requires employee to have access to this organization.
    
    Args:
        organization_id: Organization ID.
        user: Authenticated user.
        employee_service: Employee service dependency.
        service: Organization service dependency.
        
    Returns:
        Organization details.
        
    Raises:
        HTTPException: If organization not found or access denied.
    """
    # Verify employee has access to this organization
    await verify_organization_access(user, organization_id, employee_service)
    
    organization = await service.get_by_id(organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return organization


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
):
    """Create a new organization.
    
    Requires authentication. Any authenticated user can create an organization.
    
    Args:
        data: Organization creation data.
        user: Authenticated user.
        service: Organization service dependency.
        
    Returns:
        Created organization.
    """
    dto = CreateOrganizationDTO(
        name=data.name,
        code=data.code,
        address=data.address,
        phone=data.phone,
    )
    organization = await service.create(dto)
    return organization


@router.put("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: int,
    data: OrganizationUpdate,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    service: OrganizationService = Depends(get_organization_service),
):
    """Update organization.
    
    Requires administrator access in the organization.
    
    Args:
        organization_id: Organization ID.
        data: Organization update data.
        user: Authenticated user.
        employee_service: Employee service dependency.
        service: Organization service dependency.
        
    Returns:
        Updated organization.
        
    Raises:
        HTTPException: If organization not found or access denied.
    """
    # Verify user is admin in this organization
    await verify_admin_access(user, organization_id, employee_service)
    
    dto = UpdateOrganizationDTO(
        name=data.name,
        code=data.code,
        address=data.address,
        phone=data.phone,
    )
    organization = await service.update(organization_id, dto)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return organization


@router.get("/{organization_id}/employees", response_model=List[EmployeeResponse])
async def list_organization_employees(
    organization_id: int,
    include_deleted: bool = False,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Get all employees of an organization.
    
    Requires employee access to the organization.
    
    Args:
        organization_id: Organization ID.
        include_deleted: Include soft-deleted employees.
        user: Authenticated user.
        employee_service: Employee service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        List of employees.
        
    Raises:
        HTTPException: If organization not found or access denied.
    """
    # Verify user has access to this organization
    await verify_organization_access(user, organization_id, employee_service)
    
    # Verify organization exists
    organization = await organization_service.get_by_id(organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    if include_deleted:
        employees = await employee_service.get_by_organization_id_with_deleted(organization_id)
    else:
        employees = await employee_service.get_by_organization_id(organization_id)
    
    return employees


@router.delete("/{organization_id}/employees/{employee_id}", response_model=MessageResponse)
async def fire_employee(
    organization_id: int,
    employee_id: int,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Fire an employee (soft delete).
    
    Requires administrator access in the organization.
    
    Args:
        organization_id: Organization ID.
        employee_id: Employee ID.
        user: Authenticated user.
        employee_service: Employee service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If organization or employee not found, or access denied.
    """
    # Verify user is admin in this organization
    admin_employee = await verify_admin_access(user, organization_id, employee_service)
    
    # Verify organization exists
    organization = await organization_service.get_by_id(organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Verify employee exists and belongs to organization
    employee = await employee_service.get_by_id(employee_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    if employee.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee doesn't belong to this organization",
        )
    
    # Prevent self-deletion
    if employee_id == admin_employee.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot fire yourself",
        )
    
    success = await employee_service.delete(employee_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete employee",
        )
    
    return MessageResponse(message="Employee fired successfully", success=True)


@router.post("/{organization_id}/employees/{employee_id}/restore", response_model=MessageResponse)
async def restore_employee(
    organization_id: int,
    employee_id: int,
    user: User = Depends(get_current_user),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Restore a soft-deleted employee.
    
    Requires administrator access in the organization.
    
    Args:
        organization_id: Organization ID.
        employee_id: Employee ID.
        user: Authenticated user.
        employee_service: Employee service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If organization or employee not found, or access denied.
    """
    # Verify user is admin in this organization
    await verify_admin_access(user, organization_id, employee_service)
    
    # Verify organization exists
    organization = await organization_service.get_by_id(organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Verify employee exists and belongs to organization
    employee = await employee_service.get_by_id(employee_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    if employee.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee doesn't belong to this organization",
        )
    
    success = await employee_service.restore(employee_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore employee",
        )
    
    return MessageResponse(message="Employee restored successfully", success=True)
