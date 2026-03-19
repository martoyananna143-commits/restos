"""Simplified authentication for API endpoints.

This module provides authentication without FastAPI dependency conflicts.
Use these for endpoints that need authentication but have organization_id in path.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Header, status

from app.api.deps import get_employee_service, get_user_service
from app.infra.database.models.employee.employee import Employee
from app.infra.database.models.user.user import User
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.user_service import UserService


async def get_current_user(
    x_telegram_id: int = Header(..., description="Telegram user ID"),
    x_telegram_chat_id: int = Header(..., description="Telegram chat ID"),
    user_service: UserService = Depends(get_user_service),
) -> User:
    """Get current authenticated user from Telegram headers.
    
    This requires the client to send X-Telegram-Id and X-Telegram-Chat-Id headers.
    In production, these should be validated with Telegram Web App initData.
    
    Args:
        x_telegram_id: Telegram user ID from header.
        x_telegram_chat_id: Telegram chat ID from header.
        user_service: User service dependency.
        
    Returns:
        Current user.
        
    Raises:
        HTTPException: If user not found or authentication failed.
    """
    if not x_telegram_id or not x_telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication headers",
        )
    
    # Get user by telegram_id
    users = await user_service.get_by_telegram_id(x_telegram_id)
    
    if not users:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    # For now, return the first user
    # In production, you might want to verify chat_id or have more sophisticated logic
    return users[0]


async def verify_organization_access(
    user: User,
    organization_id: int,
    employee_service: EmployeeService,
) -> Employee:
    """Verify user has access to organization and return employee.
    
    Helper function to check organization access.
    Call this inside your endpoint functions.
    
    Args:
        user: Current authenticated user.
        organization_id: Organization ID to check access for.
        employee_service: Employee service dependency.
        
    Returns:
        Employee in the organization.
        
    Raises:
        HTTPException: If user doesn't have access to organization.
    """
    # Get employee by telegram_id and organization_id
    employees = await employee_service.get_by_organization_id(organization_id)
    
    employee = next(
        (e for e in employees if e.telegram_id == user.telegram_id),
        None
    )
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    if employee.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this organization has been revoked",
        )
    
    return employee


async def verify_admin_access(
    user: User,
    organization_id: int,
    employee_service: EmployeeService,
) -> Employee:
    """Verify user is admin in organization and return employee.
    
    Helper function to check admin access.
    Call this inside your endpoint functions.
    
    Args:
        user: Current authenticated user.
        organization_id: Organization ID to check admin access for.
        employee_service: Employee service dependency.
        
    Returns:
        Employee if they are admin in the organization.
        
    Raises:
        HTTPException: If user is not admin in organization.
    """
    employee = await verify_organization_access(user, organization_id, employee_service)
    
    if not employee.is_administrator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    
    return employee


async def get_optional_current_user(
    x_telegram_id: Optional[int] = Header(None, description="Telegram user ID"),
    x_telegram_chat_id: Optional[int] = Header(None, description="Telegram chat ID"),
    user_service: UserService = Depends(get_user_service),
) -> Optional[User]:
    """Get current user if authenticated, None otherwise.
    
    Used for endpoints that can work both authenticated and unauthenticated.
    
    Args:
        x_telegram_id: Optional Telegram user ID from header.
        x_telegram_chat_id: Optional Telegram chat ID from header.
        user_service: User service dependency.
        
    Returns:
        Current user or None.
    """
    if not x_telegram_id or not x_telegram_chat_id:
        return None
    
    try:
        users = await user_service.get_by_telegram_id(x_telegram_id)
        return users[0] if users else None
    except Exception:
        return None
