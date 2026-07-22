"""Web authentication router — JWT-based auth for the standalone web app.

Credentials are stored in the employee.meta JSONB field (no DB migration needed):
  meta["web_login"]        — unique login / username
  meta["hashed_password"]  — bcrypt hash of the main login password (always required to sign in)
  meta["hashed_web_pin"]   — optional bcrypt hash of a 6-digit second factor (PIN); re-verified periodically
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Optional

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.api.deps import get_employee_service, get_invitation_service, get_organization_service
from app.internal.services.employee_service import EmployeeService
from app.internal.services.invitation_service import InvitationService
from app.internal.services.organization_service import OrganizationService
from app.infra.database.repository.employee.dto import CreateEmployeeDTO
from app.infra.database.repository.organization.dto import CreateOrganizationDTO

router = APIRouter(prefix="/web/auth", tags=["web-auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/web/auth/login")
# auto_error=False so query-param token fallback works for file downloads
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/web/auth/login", auto_error=False)

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


def _normalize_meta(raw_meta) -> dict:
    """Normalize JSONB meta that may come as dict/string/None."""
    if raw_meta is None:
        return {}
    if isinstance(raw_meta, dict):
        return raw_meta
    if isinstance(raw_meta, str):
        if not raw_meta.strip():
            return {}
        try:
            parsed = json.loads(raw_meta)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


# ── Pydantic schemas ────────────────────────────────────────────────────────

class OrgInfoOut(BaseModel):
    id: int
    name: str


class RegisterRequest(BaseModel):
    invite_code: str
    full_name: str
    login: str
    password: str
    org_name: Optional[str] = None  # Required for standalone (create-org) invites


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee_id: int
    org_id: int
    name: str
    is_admin: bool
    is_superuser: bool = False
    available_orgs: list[OrgInfoOut] = []


class MeResponse(BaseModel):
    employee_id: int
    org_id: int
    name: str
    is_admin: bool
    is_superuser: bool = False
    position: Optional[str] = None
    organization_name: Optional[str] = None
    available_orgs: list[OrgInfoOut] = []
    web_login: Optional[str] = None
    has_password: bool = False
    has_pin: bool = False
    pin_required_now: bool = False
    is_org_creator: bool = False
    is_employee_role: bool = False


class SetWebPinRequest(BaseModel):
    """Установка или смена дополнительного PIN (не заменяет пароль входа)."""

    login_password: str
    new_pin: str = Field(..., pattern=r"^\d{6}$")


class VerifyPinRequest(BaseModel):
    pin: str = Field(..., pattern=r"^\d{6}$")


class StandaloneInviteRequest(BaseModel):
    ttl_seconds: int = 86400 * 30  # 30 days default


class SwitchOrgRequest(BaseModel):
    org_id: int


class CreateOrgRequest(BaseModel):
    name: str
    code: Optional[str] = None


# ── JWT helpers ──────────────────────────────────────────────────────────────

def _create_token(
    employee_id: int,
    org_id: int,
    is_superuser: bool = False,
    *,
    pin_verified_at: Optional[int] = None,
) -> str:
    cfg = _cfg()
    expire = datetime.now(timezone.utc) + timedelta(days=cfg.JWT_EXPIRE_DAYS)
    payload: dict = {"sub": str(employee_id), "org": org_id, "exp": expire}
    if is_superuser:
        payload["su"] = True
    if pin_verified_at is not None:
        payload["pva"] = int(pin_verified_at)
    return jwt.encode(payload, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)


def _meta_has_pin(meta: dict) -> bool:
    hp = meta.get("hashed_web_pin") or ""
    return isinstance(hp, str) and bool(hp.strip())


def _pin_session_ok(meta: dict, jwt_payload: dict) -> bool:
    if not _meta_has_pin(meta):
        return True
    pva = jwt_payload.get("pva")
    if pva is None:
        return False
    try:
        pva_int = int(pva)
    except (TypeError, ValueError):
        return False
    if pva_int <= 0:
        return False
    cfg = _cfg()
    max_age = int(getattr(cfg, "WEB_PIN_MAX_AGE_SECONDS", 86400))
    now = int(datetime.now(timezone.utc).timestamp())
    return now - pva_int <= max_age


def _login_issue_pva(meta: Optional[dict]) -> Optional[int]:
    if not _meta_has_pin(meta or {}):
        return None
    return 0


def _reissue_pva(old_payload: dict, subject_meta: dict) -> Optional[int]:
    if not _meta_has_pin(subject_meta):
        return None
    if "pva" in old_payload:
        try:
            return int(old_payload["pva"])
        except (TypeError, ValueError):
            return 0
    return 0


def _now_pva() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _is_superuser_login(web_login: str) -> bool:
    """Check if this login is the configured superuser."""
    cfg = _cfg()
    return bool(cfg.SUPERUSER_LOGIN and web_login == cfg.SUPERUSER_LOGIN)


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


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_available_orgs(
    web_login: str,
    employee_service: EmployeeService,
    org_service: OrganizationService,
    is_superuser: bool = False,
) -> list[OrgInfoOut]:
    """Return all organizations accessible to this login.

    For superusers returns every org in the system.
    For regular users returns only orgs where they have an employee record.
    """
    if is_superuser:
        all_orgs = await org_service.get_all()
        return [OrgInfoOut(id=o.id, name=o.name) for o in all_orgs]

    all_emps = await employee_service.get_all_by_web_login(web_login)
    seen_org_ids: set[int] = set()
    result: list[OrgInfoOut] = []
    for emp in all_emps:
        if emp.organization_id in seen_org_ids:
            continue
        seen_org_ids.add(emp.organization_id)
        org = await org_service.get_by_id(emp.organization_id)
        if org:
            result.append(OrgInfoOut(id=org.id, name=org.name))
    return result


@dataclass
class WebAuthContext:
    employee: object
    payload: dict


async def _web_auth_context_from_token(token: str, employee_service: EmployeeService) -> WebAuthContext:
    payload = _decode_token(token)
    try:
        emp_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    emp = await employee_service.get_by_id(emp_id)
    if not emp or emp.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Employee not found")
    return WebAuthContext(employee=_apply_superuser_org_override(emp, payload), payload=payload)


async def _issue_token_response(
    employee_service: EmployeeService,
    org_service: OrganizationService,
    emp,
    *,
    org_id: Optional[int] = None,
    is_superuser: Optional[bool] = None,
    pin_verified_at: Optional[int] = None,
) -> TokenResponse:
    oid = org_id if org_id is not None else emp.organization_id
    meta = emp.meta or {}
    web_login = meta.get("web_login", "")
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    is_ad = bool(my_type.get("is_administrator", False))
    is_su_meta = bool(meta.get("is_superuser", False))
    is_su = is_superuser if is_superuser is not None else is_su_meta
    is_admin = is_ad or is_su
    available = (
        await _get_available_orgs(web_login, employee_service, org_service, is_superuser=is_su)
        if web_login
        else []
    )
    tok = _create_token(emp.id, oid, is_superuser=is_su, pin_verified_at=pin_verified_at)
    return TokenResponse(
        access_token=tok,
        employee_id=emp.id,
        org_id=oid,
        name=emp.full_name,
        is_admin=is_admin,
        is_superuser=is_su,
        available_orgs=available,
    )


async def _is_org_creator(
    emp,
    employee_service: EmployeeService,
    org_service: OrganizationService,
) -> bool:
    """Determine whether current employee is creator of active organization."""
    org = await org_service.get_by_id(emp.organization_id)
    if not org:
        return False

    org_meta = _normalize_meta(getattr(org, "meta", {}))
    creator_id = org_meta.get("created_by_employee_id")
    if creator_id is not None:
        try:
            return int(creator_id) == int(emp.id)
        except (TypeError, ValueError):
            return False

    # Legacy fallback for older organizations without creator metadata.
    emp_types = await employee_service.get_employee_types()
    admin_type_ids = {
        int(t["id"]) for t in emp_types if bool(t.get("is_administrator", False))
    }
    org_employees = await employee_service.get_by_organization_id(emp.organization_id)
    admins = [e for e in org_employees if int(e.employee_type_id) in admin_type_ids]
    if not admins:
        return False
    first_admin = min(admins, key=lambda e: e.created_at)
    return int(first_admin.id) == int(emp.id)


# ── Auth dependency — inject into any web endpoint ──────────────────────────

def _apply_superuser_org_override(emp, payload: dict):
    """For superuser tokens, override the employee's organization_id with the
    JWT's ``org`` claim so all org-based filters use the active org context
    rather than the superuser's home org.

    Returns a copy of the DTO (or the same object) with ``organization_id`` set
    to the active org and ``meta["is_superuser"] = True`` injected.
    """
    if not payload.get("su"):
        return emp

    jwt_org_id = int(payload.get("org", emp.organization_id))
    # Shallow-copy the dataclass so we don't mutate the cached object
    import dataclasses
    overridden = dataclasses.replace(
        emp,
        organization_id=jwt_org_id,
        meta={**emp.meta, "is_superuser": True},
    )
    return overridden


async def get_web_auth_context(
    token: str = Depends(oauth2_scheme),
    employee_service: EmployeeService = Depends(get_employee_service),
) -> WebAuthContext:
    return await _web_auth_context_from_token(token, employee_service)


async def get_current_web_employee(ctx: WebAuthContext = Depends(get_web_auth_context)):
    """Decode JWT and return the Employee DTO (no second-factor check)."""
    return ctx.employee


async def get_current_web_employee_pin_fresh(ctx: WebAuthContext = Depends(get_web_auth_context)):
    """Like ``get_current_web_employee`` but requires a fresh PIN proof in the JWT when a PIN is configured."""
    if not _pin_session_ok(ctx.employee.meta or {}, ctx.payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pin_required")
    return ctx.employee


async def get_web_auth_context_pin_fresh(ctx: WebAuthContext = Depends(get_web_auth_context)) -> WebAuthContext:
    """Context with the same PIN freshness requirement as ``get_current_web_employee_pin_fresh``."""
    if not _pin_session_ok(ctx.employee.meta or {}, ctx.payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pin_required")
    return ctx


async def get_current_web_employee_download(
    header_token: Optional[str] = Depends(oauth2_scheme_optional),
    access_token: Optional[str] = Query(None),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Auth dependency for file downloads (Bearer header OR ?access_token= query param)."""
    token = header_token or access_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    ctx = await _web_auth_context_from_token(token, employee_service)
    if not _pin_session_ok(ctx.employee.meta or {}, ctx.payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pin_required")
    return ctx.employee


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Register a new web user using an invitation code.

    For standalone (create-org) invites the ``org_name`` field is required and
    a new organization is created automatically.
    """
    invite = await invitation_service.get_invitation(data.invite_code)
    if not invite:
        raise HTTPException(status_code=400, detail="Invite code invalid or expired")
    if invite.get("used", False):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation link has already been used",
        )

    is_standalone = bool(invite.get("standalone", False))

    # ── Org resolution ───────────────────────────────────────────────────────
    if is_standalone:
        if not data.org_name or not data.org_name.strip():
            raise HTTPException(status_code=400, detail="org_name is required for standalone invites")
        import re, secrets as _sec
        _raw_slug = re.sub(r"[^a-z0-9]+", "-", data.org_name.strip().lower()).strip("-")[:32]
        slug = (_raw_slug or "org") + "-" + _sec.token_hex(4)
        new_org = await org_service.create(CreateOrganizationDTO(name=data.org_name.strip(), code=slug))
        org_id = new_org.id
    else:
        raw_org_id = invite.get("organization_id")
        if raw_org_id is None:
            raise HTTPException(status_code=400, detail="Invite has no organization — contact support")
        org_id = int(raw_org_id)

    # Check login uniqueness globally (same login can't register twice)
    existing = await employee_service.get_by_web_login(data.login)
    if existing:
        raise HTTPException(status_code=409, detail="Login already taken")

    # ── Employee type ────────────────────────────────────────────────────────
    emp_types = await employee_service.get_employee_types()
    if not emp_types:
        raise HTTPException(status_code=500, detail="No employee types configured")

    if is_standalone:
        # Standalone registrant becomes admin of their new org
        emp_type = next(
            (t for t in emp_types if t.get("is_administrator", False)),
            emp_types[0],
        )
    else:
        invite_type_id = invite.get("employee_type_id")
        emp_type = (
            next((t for t in emp_types if t["id"] == invite_type_id), None)
            if invite_type_id is not None
            else None
        )
        if emp_type is None:
            emp_type = next(
                (t for t in emp_types if not t.get("is_administrator", False)),
                emp_types[0],
            )

    # ── Create employee ──────────────────────────────────────────────────────
    hashed = _hash_password(data.password)
    dto = CreateEmployeeDTO(
        organization_id=org_id,
        employee_type_id=emp_type["id"],
        full_name=data.full_name,
        position=invite.get("position"),
        meta={"web_login": data.login, "hashed_password": hashed},
    )
    new_emp = await employee_service.create(dto)
    await invitation_service.use_invitation(data.invite_code)

    # ── Also create a default evaluation type for new standalone orgs ────────
    if is_standalone:
        try:
            from app.infra.database.repository.evaluation_type.dto import CreateEvaluationTypeDTO
            from app.infra.database.repository.evaluation_type.evaluation_type_asyncpg import EvaluationTypeRepositoryAsyncpg
            from app.internal.services.evaluation_type_service import EvaluationTypeService
            # Inline creation — avoids importing pool at module level
            from app.api.deps import get_organization_service as _go  # noqa: F401
            from app.internal import Container
            pool = await Container().postgresql_resource()
            et_svc = EvaluationTypeService(EvaluationTypeRepositoryAsyncpg(pool))
            await et_svc.create(CreateEvaluationTypeDTO(
                organization_id=org_id,
                name="Стандартная оценка",
                code="standard",
                description="Стандартный тип оценки",
            ))
        except Exception:
            pass  # Non-critical; admin can create manually

    is_admin = bool(emp_type.get("is_administrator", False))
    is_su = _is_superuser_login(data.login)
    token = _create_token(
        new_emp.id,
        org_id,
        is_superuser=is_su,
        pin_verified_at=_login_issue_pva(new_emp.meta),
    )
    available = await _get_available_orgs(data.login, employee_service, org_service, is_superuser=is_su)
    return TokenResponse(
        access_token=token,
        employee_id=new_emp.id,
        org_id=org_id,
        name=new_emp.full_name,
        is_admin=is_admin or is_su,
        is_superuser=is_su,
        available_orgs=available,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Login with login + password (OAuth2 password form)."""
    emp = await employee_service.get_by_web_login(form.username)
    if not emp:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    hashed = emp.meta.get("hashed_password", "")
    if not hashed or not _verify_password(form.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    is_admin = bool(my_type.get("is_administrator", False))
    is_su = _is_superuser_login(form.username)

    available = await _get_available_orgs(form.username, employee_service, org_service, is_superuser=is_su)
    token = _create_token(
        emp.id,
        emp.organization_id,
        is_superuser=is_su,
        pin_verified_at=_login_issue_pva(emp.meta),
    )
    return TokenResponse(
        access_token=token,
        employee_id=emp.id,
        org_id=emp.organization_id,
        name=emp.full_name,
        is_admin=is_admin or is_su,
        is_superuser=is_su,
        available_orgs=available,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    ctx: WebAuthContext = Depends(get_web_auth_context),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Return current user profile."""
    emp = ctx.employee
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    is_admin = bool(my_type.get("is_administrator", False))
    my_code = str(my_type.get("code", "")).strip().lower()
    is_employee_role = my_code == "employee"
    web_login = emp.meta.get("web_login", "")
    is_su = bool(emp.meta.get("is_superuser", False))
    available = await _get_available_orgs(web_login, employee_service, org_service, is_superuser=is_su) if web_login else []
    org = await org_service.get_by_id(emp.organization_id)
    meta = emp.meta or {}
    hp = meta.get("hashed_password") or ""
    has_pw = bool(isinstance(hp, str) and hp.strip())
    has_pin = _meta_has_pin(meta)
    pin_required_now = has_pin and not _pin_session_ok(meta, ctx.payload)
    is_org_creator = await _is_org_creator(emp, employee_service, org_service)
    wl = (web_login or "").strip() or None
    return MeResponse(
        employee_id=emp.id,
        org_id=emp.organization_id,
        name=emp.full_name,
        is_admin=is_admin or is_su,
        is_superuser=is_su,
        position=emp.position,
        organization_name=org.name if org else None,
        available_orgs=available,
        web_login=wl,
        has_password=has_pw,
        has_pin=has_pin,
        pin_required_now=pin_required_now,
        is_org_creator=is_org_creator,
        is_employee_role=is_employee_role,
    )


async def _sync_hashed_web_pin_for_login(
    employee_service: EmployeeService,
    web_login: str,
    pin_hash: str,
) -> None:
    rows = await employee_service.get_all_by_web_login(web_login)
    for row in rows:
        m = dict(row.meta or {})
        m["hashed_web_pin"] = pin_hash
        ok = await employee_service.update_meta(row.id, m)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось сохранить PIN-код",
            )


@router.post("/pin", response_model=TokenResponse)
async def set_web_pin(
    data: SetWebPinRequest,
    ctx: WebAuthContext = Depends(get_web_auth_context),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Set or change the optional second-factor PIN (main login password unchanged)."""
    emp = ctx.employee
    meta = emp.meta or {}
    web_login = (meta.get("web_login") or "").strip()
    if not web_login:
        raise HTTPException(status_code=400, detail="No web login associated with account")

    raw_hash = meta.get("hashed_password") or ""
    if not raw_hash or not _verify_password(data.login_password, raw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль входа")

    pin_hash = _hash_password(data.new_pin)
    await _sync_hashed_web_pin_for_login(employee_service, web_login, pin_hash)

    pva = _now_pva()
    return await _issue_token_response(
        employee_service,
        org_service,
        emp,
        pin_verified_at=pva,
    )


@router.post("/verify-pin", response_model=TokenResponse)
async def verify_web_pin(
    data: VerifyPinRequest,
    ctx: WebAuthContext = Depends(get_web_auth_context),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Confirm the second-factor PIN and receive a JWT with a fresh ``pva`` claim."""
    emp = ctx.employee
    meta = emp.meta or {}
    if not _meta_has_pin(meta):
        raise HTTPException(status_code=400, detail="PIN не настроен")

    pin_hash = meta.get("hashed_web_pin") or ""
    if not pin_hash or not _verify_password(data.pin, pin_hash):
        raise HTTPException(status_code=400, detail="Неверный PIN-код")

    return await _issue_token_response(
        employee_service,
        org_service,
        emp,
        pin_verified_at=_now_pva(),
    )


# ── Invite info (public) ─────────────────────────────────────────────────────

class InviteInfoResponse(BaseModel):
    valid: bool
    is_standalone: bool = False
    organization_name: Optional[str] = None


@router.get("/invite-info/{code}", response_model=InviteInfoResponse)
async def invite_info(
    code: str,
    invitation_service: InvitationService = Depends(get_invitation_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Return public metadata about an invite (validity + type) without exposing internals."""
    invite = await invitation_service.get_invitation(code)
    if not invite or invite.get("used", False):
        return InviteInfoResponse(valid=False)

    is_standalone = bool(invite.get("standalone", False))
    org_name: Optional[str] = None
    if not is_standalone:
        raw_org_id = invite.get("organization_id")
        if raw_org_id is not None:
            org = await org_service.get_by_id(int(raw_org_id))
            if org:
                org_name = org.name

    return InviteInfoResponse(valid=True, is_standalone=is_standalone, organization_name=org_name)


# ── Standalone invite (admin → new org) ─────────────────────────────────────

@router.post("/invite-standalone", status_code=status.HTTP_201_CREATED)
async def create_standalone_invite(
    data: StandaloneInviteRequest,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    invitation_service: InvitationService = Depends(get_invitation_service),
):
    """Create a standalone invite — the recipient will register and create their own org.

    Only admins can create standalone invites.
    """
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    if not my_type.get("is_administrator", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    code = await invitation_service.create_invitation(
        inviter_telegram_id=None,
        organization_id=None,
        invitation_type="standalone",
        created_by_employee_id=emp.id,
        ttl=data.ttl_seconds,
    )

    # Patch the stored invitation to mark it as standalone
    invite = await invitation_service.get_invitation(code)
    if invite:
        invite["standalone"] = True
        import json as _json
        from app.internal.services.invitation_service import InvitationService as _IS
        redis_key = invitation_service._get_redis_key(code)
        raw = _json.dumps(invite, ensure_ascii=False)
        if hasattr(invitation_service.storage, "_redis") and invitation_service.storage._redis:
            await invitation_service.storage._redis.set(redis_key, raw, ex=data.ttl_seconds)
        elif hasattr(invitation_service.storage, "redis"):
            await invitation_service.storage.redis.set(redis_key, raw, ex=data.ttl_seconds)

    from app.settings import config
    invite_url = f"{config.WEBAPP_BASE_URL or ''}/?invite_code={code}&auth=register" if hasattr(config, "WEBAPP_BASE_URL") else f"/?invite_code={code}&auth=register"
    return {"code": code, "invite_url": invite_url, "ttl_seconds": data.ttl_seconds}


# ── Org management ────────────────────────────────────────────────────────────

@router.get("/orgs", response_model=list[OrgInfoOut])
async def list_my_orgs(
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """List all organizations the current user has access to.

    Superusers receive all organizations in the system.
    """
    web_login = emp.meta.get("web_login", "")
    if not web_login:
        return []
    is_su = bool(emp.meta.get("is_superuser", False))
    return await _get_available_orgs(web_login, employee_service, org_service, is_superuser=is_su)


@router.post("/switch-org", response_model=TokenResponse)
async def switch_org(
    data: SwitchOrgRequest,
    ctx: WebAuthContext = Depends(get_web_auth_context_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Re-issue a JWT for a different organization the current user has access to."""
    emp = ctx.employee
    web_login = emp.meta.get("web_login", "")
    if not web_login:
        raise HTTPException(status_code=400, detail="No web login associated with account")

    is_su = bool(emp.meta.get("is_superuser", False))

    # Verify target org exists
    target_org = await org_service.get_by_id(data.org_id)
    if not target_org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if is_su:
        return await _issue_token_response(
            employee_service,
            org_service,
            emp,
            org_id=data.org_id,
            is_superuser=True,
            pin_verified_at=_reissue_pva(ctx.payload, emp.meta or {}),
        )

    # Regular user: must have an employee record in the target org
    all_emps = await employee_service.get_all_by_web_login(web_login)
    target_emp = next((e for e in all_emps if e.organization_id == data.org_id), None)
    if not target_emp:
        raise HTTPException(status_code=403, detail="No access to this organization")

    return await _issue_token_response(
        employee_service,
        org_service,
        target_emp,
        org_id=data.org_id,
        is_superuser=False,
        pin_verified_at=_reissue_pva(ctx.payload, target_emp.meta or {}),
    )


@router.post("/create-org", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    data: CreateOrgRequest,
    ctx: WebAuthContext = Depends(get_web_auth_context_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    org_service: OrganizationService = Depends(get_organization_service),
):
    """Create a new organization and make the current user its admin.

    Only existing admins can create additional organizations.
    """
    emp = ctx.employee
    is_su = bool(emp.meta.get("is_superuser", False))
    emp_types = await employee_service.get_employee_types()
    my_type = next((t for t in emp_types if t["id"] == emp.employee_type_id), {})
    if not my_type.get("is_administrator", False) and not is_su:
        raise HTTPException(status_code=403, detail="Admin access required")

    web_login = emp.meta.get("web_login", "")
    if not web_login:
        raise HTTPException(status_code=400, detail="No web login associated with account")

    import re, secrets as _sec
    _raw_code = re.sub(r"[^a-z0-9]+", "-", data.name.strip().lower()).strip("-")[:32]
    code = data.code or ((_raw_code or "org") + "-" + _sec.token_hex(4))
    new_org = await org_service.create(
        CreateOrganizationDTO(
            name=data.name.strip(),
            code=code,
            meta={
                "created_by_employee_id": emp.id,
                "created_by_telegram_id": emp.telegram_id,
            },
        )
    )

    if is_su:
        return await _issue_token_response(
            employee_service,
            org_service,
            emp,
            org_id=new_org.id,
            is_superuser=True,
            pin_verified_at=_reissue_pva(ctx.payload, emp.meta or {}),
        )

    # Find admin employee type
    admin_type = next(
        (t for t in emp_types if t.get("is_administrator", False)),
        emp_types[0],
    )

    # Create employee record in new org with same login / password / PIN
    src_meta = dict(emp.meta or {})
    hashed = src_meta.get("hashed_password", "")
    new_meta: dict = {"web_login": web_login, "hashed_password": hashed}
    if src_meta.get("hashed_web_pin"):
        new_meta["hashed_web_pin"] = src_meta["hashed_web_pin"]

    new_emp_dto = CreateEmployeeDTO(
        organization_id=new_org.id,
        employee_type_id=admin_type["id"],
        full_name=emp.full_name,
        meta=new_meta,
    )
    new_emp_record = await employee_service.create(new_emp_dto)

    # Create a default evaluation type for the new org
    try:
        from app.infra.database.repository.evaluation_type.dto import CreateEvaluationTypeDTO
        from app.infra.database.repository.evaluation_type.evaluation_type_asyncpg import EvaluationTypeRepositoryAsyncpg
        from app.internal.services.evaluation_type_service import EvaluationTypeService
        from app.internal import Container
        pool = await Container().postgresql_resource()
        et_svc = EvaluationTypeService(EvaluationTypeRepositoryAsyncpg(pool))
        await et_svc.create(CreateEvaluationTypeDTO(
            organization_id=new_org.id,
            name="Стандартная оценка",
            code="standard",
            description="Стандартный тип оценки",
        ))
    except Exception:
        pass

    return await _issue_token_response(
        employee_service,
        org_service,
        new_emp_record,
        org_id=new_org.id,
        is_superuser=False,
        pin_verified_at=_reissue_pva(ctx.payload, new_emp_record.meta or {}),
    )
