"""Employees API router."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_employee, require_admin
from app.api.deps import get_employee_service, get_organization_service
from app.api.schemas import (
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    MessageResponse,
)
from app.infra.database.models.employee.employee import Employee
from app.infra.database.repository.employee.dto import (
    CreateEmployeeDTO,
    UpdateEmployeeDTO,
)
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.organization_service import OrganizationService

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=List[EmployeeResponse])
async def list_employees(
    organization_id: int,
    include_deleted: bool = False,
    employee: Employee = Depends(get_current_employee),
    service: EmployeeService = Depends(get_employee_service),
):
    """Get employees list.
    
    Requires employee access to the organization.
    
    Args:
        organization_id: Organization ID (from X-Organization-Id header).
        include_deleted: Include soft-deleted employees.
        employee: Authenticated employee in organization.
        service: Employee service dependency.
        
    Returns:
        List of employees.
        
    Raises:
        HTTPException: If access denied.
    """
    # Verify employee has access to this organization
    if employee.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    if include_deleted:
        employees = await service.get_by_organization_id_with_deleted(organization_id)
    else:
        employees = await service.get_by_organization_id(organization_id)
    
    return employees


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: int,
    current_employee: Employee = Depends(get_current_employee),
    service: EmployeeService = Depends(get_employee_service),
):
    """Get employee by ID.
    
    Requires employee access to the same organization.
    
    Args:
        employee_id: Employee ID.
        current_employee: Authenticated employee.
        service: Employee service dependency.
        
    Returns:
        Employee details.
        
    Raises:
        HTTPException: If employee not found or access denied.
    """
    employee = await service.get_by_id(employee_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    # Verify access to same organization
    if employee.organization_id != current_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this employee",
        )
    
    return employee


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    data: EmployeeCreate,
    admin_employee: Employee = Depends(require_admin),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Create a new employee.
    
    Requires administrator access in the organization.
    
    Args:
        data: Employee creation data.
        admin_employee: Authenticated admin employee.
        employee_service: Employee service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Created employee.
        
    Raises:
        HTTPException: If organization not found or access denied.
    """
    # Verify admin has access to this organization
    if admin_employee.organization_id != data.organization_id:
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
    
    dto = CreateEmployeeDTO(
        organization_id=data.organization_id,
        employee_type_id=data.employee_type_id,
        full_name=data.full_name,
        position=data.position,
        phone=data.phone,
        telegram_id=data.telegram_id,
    )
    employee = await employee_service.create(dto)
    return employee


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    data: EmployeeUpdate,
    admin_employee: Employee = Depends(require_admin),
    service: EmployeeService = Depends(get_employee_service),
):
    """Update employee.
    
    Requires administrator access in the same organization.
    
    Args:
        employee_id: Employee ID.
        data: Employee update data.
        admin_employee: Authenticated admin employee.
        service: Employee service dependency.
        
    Returns:
        Updated employee.
        
    Raises:
        HTTPException: If employee not found or access denied.
    """
    # Get existing employee
    existing = await service.get_by_id(employee_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    # Verify admin has access to employee's organization
    if existing.organization_id != admin_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this employee",
        )
    
    dto = UpdateEmployeeDTO(
        full_name=data.full_name,
        position=data.position,
        phone=data.phone,
    )
    employee = await service.update(employee_id, dto)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    return employee


@router.delete("/{employee_id}", response_model=MessageResponse)
async def delete_employee(
    employee_id: int,
    admin_employee: Employee = Depends(require_admin),
    service: EmployeeService = Depends(get_employee_service),
):
    """Delete employee (soft delete).
    
    Requires administrator access in the same organization.
    
    Args:
        employee_id: Employee ID.
        admin_employee: Authenticated admin employee.
        service: Employee service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If employee not found or access denied.
    """
    # Get existing employee
    existing = await service.get_by_id(employee_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    # Verify admin has access to employee's organization
    if existing.organization_id != admin_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this employee",
        )
    
    # Prevent self-deletion
    if employee_id == admin_employee.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    
    success = await service.delete(employee_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete employee",
        )
    
    return MessageResponse(message="Employee deleted successfully", success=True)


@router.post("/{employee_id}/restore", response_model=MessageResponse)
async def restore_employee(
    employee_id: int,
    admin_employee: Employee = Depends(require_admin),
    service: EmployeeService = Depends(get_employee_service),
):
    """Restore a soft-deleted employee.
    
    Requires administrator access in the same organization.
    
    Args:
        employee_id: Employee ID.
        admin_employee: Authenticated admin employee.
        service: Employee service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If employee not found or access denied.
    """
    # Verify employee exists
    employee = await service.get_by_id(employee_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    
    # Verify admin has access to employee's organization
    if employee.organization_id != admin_employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this employee",
        )
    
    success = await service.restore(employee_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore employee",
        )
    
    return MessageResponse(message="Employee restored successfully", success=True)


@router.get("/telegram/{telegram_id}", response_model=EmployeeResponse)
async def get_employee_by_telegram_id(
    telegram_id: int,
    organization_id: Optional[int] = None,
    service: EmployeeService = Depends(get_employee_service),
):
    """Get employee by Telegram ID.
    
    Args:
        telegram_id: Telegram user ID.
        organization_id: Optional organization ID filter.
        service: Employee service dependency.
        
    Returns:
        Employee details.
        
    Raises:
        HTTPException: If employee not found.
    """
    if organization_id:
        employee = await service.get_by_telegram_id_and_organization_id(
            telegram_id, organization_id
        )
    else:
        employee = await service.get_by_telegram_id(telegram_id)
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    return employee
