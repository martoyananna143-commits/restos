"""Web authentication router — JWT-based auth for the standalone web app.

Credentials are stored in the employee.meta JSONB field (no DB migration needed):
  meta["web_login"]        — unique login name
  meta["hashed_password"]  — bcrypt hash
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from app.api.deps import get_employee_service, get_invitation_service
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.invitation_service import InvitationService
from app.infra.database.repository.employee.dto import CreateEmployeeDTO

router = APIRouter(prefix="/web/auth", tags=["web-auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/web/auth/login")

# bcrypt limit: 72 bytes; truncate to avoid error
def _hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.checkpw(pwd_bytes, hashed.encode())


def _cfg():
    from app.settings import config
    return config


# ── Pydantic schemas ────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    invite_code: str
    full_name: str
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee_id: int
    org_id: int
    name: str
    is_admin: bool


class MeResponse(BaseModel):
    employee_id: int
    org_id: int
    name: str
    is_admin: bool
    position: Optional[str] = None
    organization_name: Optional[str] = None


# ── JWT helpers ──────────────────────────────────────────────────────────────

def _create_token(employee_id: int, org_id: int) -> str:
    cfg = _cfg()
    expire = datetime.now(timezone.utc) + timedelta(days=cfg.JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(employee_id), "org": org_id, "exp": expire},
        cfg.JWT_SECRET_KEY,
        algorithm=cfg.JWT_ALGORITHM,
    )


def _decode_token(token: str) -> dict:
    cfg = _cfg()
    try:
        return jwt.decode(token, cfg.JWT_SECRET_KEY, algorithms=[cfg.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Auth dependency — inject into any web endpoint ──────────────────────────

async def get_current_web_employee(
    token: str = Depends(oauth2_scheme),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Decode JWT and return the Employee DTO."""
    payload = _decode_token(token)
    try:
        emp_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    emp = await employee_service.get_by_id(emp_id)
    if not emp or emp.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Employee not found")
    return emp


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
):
    """Register a new web user using an invitation code."""
    invite = await invitation_service.get_invitation(data.invite_code)
    if not invite:
        raise HTTPException(status_code=400, detail="Invite code invalid or expired")
    org_id: int = invite["organization_id"]

    # Check login uniqueness in this org
    existing = await employee_service.get_by_web_login(data.login)
    if existing:
        raise HTTPException(status_code=409, detail="Login already taken")

    # Get first non-admin employee type for this org
    emp_types = await employee_service.get_employee_types()
    if not emp_types:
        raise HTTPException(status_code=500, detail="No employee types configured")
    emp_type = next(
        (t for t in emp_types if not t.get("is_administrator", False)),
        emp_types[0],
    )

    # Create employee with credentials in meta
    hashed = _hash_password(data.password)
    dto = CreateEmployeeDTO(
        organization_id=org_id,
        employee_type_id=emp_type["id"],
        full_name=data.full_name,
        meta={"web_login": data.login, "hashed_password": hashed},
    )
    new_emp = await employee_service.create(dto)

    await invitation_service.use_invitation(data.invite_code)

    token = _create_token(new_emp.id, org_id)
    return TokenResponse(
        access_token=token,
        employee_id=new_emp.id,
        org_id=org_id,
        name=new_emp.full_name,
        is_admin=bool(emp_type.get("is_administrator", False)),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Login with login + password (OAuth2 password form)."""
    emp = await employee_service.get_by_web_login(form.username)
    if not emp:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    hashed = emp.meta.get("hashed_password", "")
    if not hashed or not _verify_password(form.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Determine if admin by looking up employee types
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    is_admin = bool(my_type.get("is_administrator", False))

    token = _create_token(emp.id, emp.organization_id)
    return TokenResponse(
        access_token=token,
        employee_id=emp.id,
        org_id=emp.organization_id,
        name=emp.full_name,
        is_admin=is_admin,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    emp=Depends(get_current_web_employee),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Return current user profile."""
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    is_admin = bool(my_type.get("is_administrator", False))
    return MeResponse(
        employee_id=emp.id,
        org_id=emp.organization_id,
        name=emp.full_name,
        is_admin=is_admin,
        position=emp.position,
    )
