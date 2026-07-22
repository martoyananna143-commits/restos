"""Invitations API router."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_admin
from app.api.deps import get_invitation_service, get_organization_service
from app.api.schemas import (
    InvitationCreate,
    InvitationResponse,
    MessageResponse,
)
from app.infra.database.models.employee.employee import Employee
from app.internal.services.invitation_service import InvitationService
from app.internal.services.organization_service import OrganizationService

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    data: InvitationCreate,
    employee: Employee = Depends(require_admin),
    invitation_service: InvitationService = Depends(get_invitation_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Create a new invitation code.
    
    Requires administrator access in the organization.
    
    Args:
        data: Invitation creation data.
        employee: Authenticated admin employee.
        invitation_service: Invitation service dependency.
        organization_service: Organization service dependency.
        
    Returns:
        Created invitation with code.
        
    Raises:
        HTTPException: If organization not found or creation fails or access denied.
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
    
    try:
        code = await invitation_service.create_invitation(
            inviter_telegram_id=data.inviter_telegram_id,
            organization_id=data.organization_id,
            ttl=data.ttl,
        )
        
        return InvitationResponse(
            code=code,
            inviter_telegram_id=data.inviter_telegram_id,
            organization_id=data.organization_id,
            used=False,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invitation: {str(e)}",
        )


@router.get("/{code}", response_model=InvitationResponse)
async def get_invitation(
    code: str,
    service: InvitationService = Depends(get_invitation_service),
):
    """Get invitation by code.
    
    Args:
        code: Invitation code.
        service: Invitation service dependency.
        
    Returns:
        Invitation details.
        
    Raises:
        HTTPException: If invitation not found.
    """
    invitation = await service.get_invitation(code)
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found or expired",
        )
    
    return InvitationResponse(
        code=code,
        inviter_telegram_id=invitation["inviter_telegram_id"],
        organization_id=invitation["organization_id"],
        used=invitation.get("used", False),
    )


@router.post("/{code}/use", response_model=InvitationResponse)
async def use_invitation(
    code: str,
    service: InvitationService = Depends(get_invitation_service),
):
    """Use an invitation code.
    
    Args:
        code: Invitation code.
        service: Invitation service dependency.
        
    Returns:
        Used invitation details.
        
    Raises:
        HTTPException: If invitation not found, expired, or already used.
    """
    invitation = await service.use_invitation(code)
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not found, expired, or already used",
        )
    
    return InvitationResponse(
        code=code,
        inviter_telegram_id=invitation["inviter_telegram_id"],
        organization_id=invitation["organization_id"],
        used=invitation.get("used", False),
    )


@router.delete("/{code}", response_model=MessageResponse)
async def delete_invitation(
    code: str,
    service: InvitationService = Depends(get_invitation_service),
):
    """Delete an invitation code.
    
    Args:
        code: Invitation code.
        service: Invitation service dependency.
        
    Returns:
        Success message.
        
    Raises:
        HTTPException: If deletion fails.
    """
    success = await service.delete_invitation(code)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )
    
    return MessageResponse(message="Invitation deleted successfully", success=True)
