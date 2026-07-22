"""Web data routes: employees and invitations."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_employee_service, get_invitation_service, get_organization_service
from app.api.routers.web_auth import get_current_web_employee_pin_fresh
from app.internal.services.employee_service import EmployeeService
from app.internal.services.invitation_service import InvitationService
from app.internal.services.organization_service import OrganizationService
from .helpers import _build_invite_url, _is_employee_role, _is_org_creator, _normalize_meta, _require_admin, _require_same_org
from .schemas import (
    EmployeeOut,
    EmployeeTypeOut,
    InvitationCreateIn,
    InvitationOut,
    UpdateRoleRequest,
)

router = APIRouter()

@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    employees = await employee_service.get_by_organization_id(emp.organization_id)
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        employees = [employee for employee in employees if employee.id == emp.id]
    type_map = {t["id"]: t for t in emp_types}
    return [
        EmployeeOut(
            id=e.id,
            full_name=e.full_name,
            position=e.position,
            employee_type_id=e.employee_type_id,
            is_admin=bool(type_map.get(e.employee_type_id, {}).get("is_administrator", False)),
            is_active=e.is_active,
        )
        for e in employees
    ]


@router.get("/employee-types", response_model=list[EmployeeTypeOut])
async def list_employee_types(
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    types = await employee_service.get_employee_types()
    return [
        EmployeeTypeOut(
            id=t["id"],
            name=t["name"],
            code=t["code"],
            is_administrator=bool(t.get("is_administrator", False)),
        )
        for t in types
    ]


@router.put("/employees/{employee_id}/role")
async def update_employee_role(
    employee_id: int,
    data: UpdateRoleRequest,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    target = await employee_service.get_by_id(employee_id)
    if not target or target.organization_id != emp.organization_id:
        raise HTTPException(status_code=404, detail="Employee not found")

    from app.infra.database.repository.employee.dto import UpdateEmployeeDTO
    updated = await employee_service.update(employee_id, UpdateEmployeeDTO(employee_type_id=data.employee_type_id))
    if not updated:
        raise HTTPException(status_code=500, detail="Update failed")
    return {"success": True}


@router.delete("/employees/{employee_id}")
async def dismiss_employee(
    employee_id: int,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Dismiss employee (soft delete), only by organization creator."""
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    org = await organization_service.get_by_id(emp.organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_employees = await employee_service.get_by_organization_id(emp.organization_id)
    if not _is_org_creator(emp, org, org_employees, emp_types):
        raise HTTPException(
            status_code=403,
            detail="Only organization creator can dismiss employees",
        )

    target = await employee_service.get_by_id(employee_id)
    if not target or target.organization_id != emp.organization_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    if target.id == emp.id:
        raise HTTPException(status_code=400, detail="Cannot dismiss yourself")

    if not await employee_service.delete(employee_id):
        raise HTTPException(status_code=500, detail="Failed to dismiss employee")
    return {"success": True}


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
):
    """List active and recently used invitations for current org (admin only)."""
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)
    type_map = {t["id"]: t["name"] for t in emp_types}

    rows = await invitation_service.list_invitations_for_organization(emp.organization_id, include_used=True)
    return [
        InvitationOut(
            code=r["code"],
            invite_url=_build_invite_url(r["code"]),
            organization_id=r["organization_id"],
            employee_type_id=r.get("employee_type_id"),
            employee_type_name=type_map.get(r.get("employee_type_id")),
            position=r.get("position"),
            full_name=r.get("full_name"),
            contact_email=r.get("contact_email"),
            contact_telegram=r.get("contact_telegram"),
            created_at=r.get("created_at"),
            expires_at=r.get("expires_at"),
            used=bool(r.get("used", False)),
        )
        for r in rows
    ]


@router.post("/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def create_invitation_web(
    data: InvitationCreateIn,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
):
    """Create employee invitation for web flow (admin only)."""
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)
    if not (data.contact_email or data.contact_telegram):
        raise HTTPException(status_code=400, detail="Specify email or telegram contact")
    if data.ttl_seconds <= 0:
        raise HTTPException(status_code=400, detail="ttl_seconds must be positive")
    target_type = next((t for t in emp_types if t["id"] == data.employee_type_id), None)
    if not target_type:
        raise HTTPException(status_code=400, detail="Invalid employee_type_id")

    code = await invitation_service.create_invitation(
        inviter_telegram_id=emp.telegram_id,
        organization_id=emp.organization_id,
        invitation_type="employee",
        employee_type_id=data.employee_type_id,
        position=data.position,
        contact_email=data.contact_email,
        contact_telegram=data.contact_telegram,
        full_name=data.full_name,
        created_by_employee_id=emp.id,
        ttl=data.ttl_seconds,
    )
    row = await invitation_service.get_invitation(code)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create invitation")

    return InvitationOut(
        code=code,
        invite_url=_build_invite_url(code),
        organization_id=emp.organization_id,
        employee_type_id=data.employee_type_id,
        employee_type_name=target_type["name"],
        position=row.get("position"),
        full_name=row.get("full_name"),
        contact_email=row.get("contact_email"),
        contact_telegram=row.get("contact_telegram"),
        created_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
        used=bool(row.get("used", False)),
    )


@router.delete("/invitations/{code}")
async def delete_invitation_web(
    code: str,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
):
    """Revoke invitation code for current organization (admin only)."""
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    invite = await invitation_service.get_invitation(code)
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.get("organization_id") != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    ok = await invitation_service.delete_invitation(code)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete invitation")
    return {"success": True}
