"""Web App API router with stateless ChaCha20 token authentication."""

import base64
import logging
import os
import time
from typing import Annotated, Optional

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.api.deps import (
    get_criterion_service,
    get_criterion_set_service,
    get_criterion_value_repository,
    get_employee_service,
    get_evaluation_service,
    get_evaluation_type_service,
    get_organization_service,
)
from app.infra.database.repository.criterion_value.criterion_value_asyncpg import CriterionValueRepositoryAsyncpg
from app.infra.database.repository.criterion_value.dto import CreateCriterionValueDTO
from app.infra.database.repository.employee.dto import UpdateEmployeeDTO
from app.infra.database.repository.evaluation.dto import CreateEvaluationDTO, UpdateEvaluationDTO
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.organization_service import OrganizationService
from app.settings import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webapp", tags=["webapp"])


# ==================== Internal key guard ====================

async def _require_internal_key(
    x_internal_key: Annotated[Optional[str], Header()] = None,
) -> None:
    """Dependency: reject requests that don't carry the correct internal API key.

    When INTERNAL_API_KEY is empty (local dev) all requests are allowed so
    existing integrations continue to work without configuration.
    """
    key = config.INTERNAL_API_KEY
    if key and x_internal_key != key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# ==================== Schemas ====================

class CriterionOut(BaseModel):
    """Criterion for the form."""
    id: int
    name: str
    code: str
    description: Optional[str] = None
    value_type: str = "boolean"
    is_required: bool = True


class FormDataResponse(BaseModel):
    """Form data response."""
    criteria: list[CriterionOut]
    organization_name: str
    evaluated_employee_name: Optional[str] = None
    criterion_set_name: Optional[str] = None


class Answer(BaseModel):
    """Single answer."""
    criterion_id: int
    value: bool | str | float
    comment: Optional[str] = None


class SubmitRequest(BaseModel):
    """Submit form request."""
    answers: list[Answer]
    comment: Optional[str] = None


class SubmitResponse(BaseModel):
    """Submit form response."""
    evaluation_id: int
    score_percentage: float
    passed_criteria: int
    failed_criteria: int
    total_criteria: int
    boolean_criteria_count: int = 0


class CreateTokenRequest(BaseModel):
    """Request to create a form token."""
    organization_id: int
    criterion_set_id: int
    filled_by_employee_id: int
    evaluated_employee_id: Optional[int] = None
    evaluation_type_id: int = 1


class CreateTokenResponse(BaseModel):
    """Response with created token."""
    token: str
    url: str


# ==================== ChaCha20 Token Utils ====================

class TokenPayload(BaseModel):
    """Token payload structure."""
    org_id: int
    set_id: int
    filler_id: int
    eval_id: Optional[int] = None
    type_id: int = 1
    exp: int  # Expiration timestamp
    nonce: str  # Random nonce for uniqueness


def _get_cipher() -> ChaCha20Poly1305:
    """Get ChaCha20Poly1305 cipher with configured key."""
    key_hex = config.WEBAPP_SECRET_KEY
    if len(key_hex) != 64:
        raise ValueError("WEBAPP_SECRET_KEY must be 64 hex characters (32 bytes)")
    key = bytes.fromhex(key_hex)
    return ChaCha20Poly1305(key)


def create_encrypted_token(
    organization_id: int,
    criterion_set_id: int,
    filled_by_employee_id: int,
    evaluated_employee_id: Optional[int] = None,
    evaluation_type_id: int = 1,
) -> str:
    """Create encrypted stateless token with all necessary data.
    
    Token format: base64url(nonce + ciphertext + tag)
    """
    # Build payload
    expiry = int(time.time()) + config.WEBAPP_TOKEN_EXPIRY
    nonce_bytes = os.urandom(12)  # 96-bit nonce for ChaCha20
    
    payload = TokenPayload(
        org_id=organization_id,
        set_id=criterion_set_id,
        filler_id=filled_by_employee_id,
        eval_id=evaluated_employee_id,
        type_id=evaluation_type_id,
        exp=expiry,
        nonce=base64.b64encode(nonce_bytes).decode(),
    )
    
    # Encrypt
    cipher = _get_cipher()
    plaintext = payload.model_dump_json().encode()
    ciphertext = cipher.encrypt(nonce_bytes, plaintext, None)
    
    # Combine: nonce (12 bytes) + ciphertext+tag
    token_bytes = nonce_bytes + ciphertext
    
    # URL-safe base64
    return base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")


def decrypt_token(token: str) -> Optional[TokenPayload]:
    """Decrypt and validate token.
    
    Returns:
        TokenPayload if valid, None if invalid or expired.
    """
    try:
        # Restore padding
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        
        token_bytes = base64.urlsafe_b64decode(token)
        
        # Split nonce and ciphertext
        if len(token_bytes) < 12:
            return None
        
        nonce_bytes = token_bytes[:12]
        ciphertext = token_bytes[12:]
        
        # Decrypt
        cipher = _get_cipher()
        plaintext = cipher.decrypt(nonce_bytes, ciphertext, None)
        
        # Parse payload
        payload = TokenPayload.model_validate_json(plaintext)
        
        # Check expiration
        if payload.exp < int(time.time()):
            return None
        
        return payload
        
    except Exception:
        return None


# ==================== Used Tokens Tracking (minimal state) ====================

# Track used tokens to prevent replay (in production, use Redis with TTL)
_used_tokens: set[str] = set()


def is_token_used(token: str) -> bool:
    """Check if token was already used."""
    return token in _used_tokens


def mark_token_used(token: str):
    """Mark token as used."""
    _used_tokens.add(token)
    # Cleanup old tokens periodically (simple approach)
    if len(_used_tokens) > 10000:
        _used_tokens.clear()


# ==================== Bot Notification Helper ====================

async def _send_export_options(
    employee_service: EmployeeService,
    filler_id: int,
    evaluation_id: int,
    score_percentage: float,
):
    """Send export options to user via bot after web form submission."""
    from app.api.main import get_shared_bot
    
    bot = get_shared_bot()
    if not bot:
        return  # Bot not available (standalone API mode)
    
    # Get employee's telegram_id
    employee = await employee_service.get_by_id(filler_id)
    if not employee or not employee.telegram_id:
        return
    
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        # Create export options buttons
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Экспорт в PDF/Excel",
                    callback_data=f"export_dialog:{evaluation_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Пропустить",
                    callback_data="back_to_greeting"
                ),
            ],
        ])
        
        message = (
            f"✅ <b>Оценка успешно сохранена!</b>\n\n"
            f"📊 Результат: <b>{score_percentage:.1f}%</b>\n"
            f"🆔 ID оценки: {evaluation_id}\n\n"
            f"Хотите экспортировать отчёт?"
        )
        
        await bot.send_message(
            employee.telegram_id,
            message,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        pass  # Silently fail if message can't be sent


# ==================== Endpoints ====================

@router.get("/form/{token}", response_model=FormDataResponse)
async def get_form_data(
    token: str,
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    organization_service: OrganizationService = Depends(get_organization_service),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Get form data for evaluation.
    
    PUBLIC ENDPOINT - Uses ChaCha20Poly1305 token authentication.
    Token contains encrypted organization_id, criterion_set_id, etc.
    
    This endpoint is intentionally public to allow web form access.
    Authorization is handled via encrypted token validation.
    """
    # Decrypt and validate token
    payload = decrypt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Форма не найдена или срок действия истек"
        )
    
    # Get organization
    organization = await organization_service.get_by_id(payload.org_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Организация не найдена"
        )
    
    # Get criterion set and verify it belongs to the organisation in the token.
    criterion_set = await criterion_set_service.get_by_id(payload.set_id)
    if not criterion_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Набор критериев не найден"
        )
    if criterion_set.organization_id != payload.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недействительный токен"
        )

    # Get criteria
    criterion_ids = criterion_set.criterion_ids or []
    criteria = await criterion_service.get_by_ids(criterion_ids)
    
    # Get evaluated employee name
    evaluated_employee_name = None
    if payload.eval_id:
        employee = await employee_service.get_by_id(payload.eval_id)
        if employee:
            evaluated_employee_name = employee.full_name
    
    return FormDataResponse(
        criteria=[
            CriterionOut(
                id=c.id,
                name=c.name,
                code=c.code,
                description=c.description,
                value_type=c.value_type,
                is_required=c.is_required,
            )
            for c in criteria
        ],
        organization_name=organization.name,
        evaluated_employee_name=evaluated_employee_name,
        criterion_set_name=criterion_set.name,
    )


@router.post("/form/{token}/submit", response_model=SubmitResponse)
async def submit_form(
    token: str,
    request: SubmitRequest,
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    criterion_value_repo=Depends(get_criterion_value_repository),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Submit form answers.

    PUBLIC ENDPOINT — access controlled via encrypted ChaCha20Poly1305 token.
    Includes replay-attack protection (token is burned after first use).
    """
    # Decrypt and validate token
    payload = decrypt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Форма не найдена или срок действия истек"
        )

    # Prevent replay attacks
    if is_token_used(token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Эта форма уже была отправлена"
        )

    # Verify the criterion set belongs to the organisation from the token
    # and that submitted answers only reference criteria from that set.
    criterion_set = await criterion_set_service.get_by_id(payload.set_id)
    if not criterion_set or criterion_set.organization_id != payload.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недействительный токен")

    allowed_criterion_ids = set(criterion_set.criterion_ids or [])
    for answer in request.answers:
        if answer.criterion_id not in allowed_criterion_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Criterion {answer.criterion_id} is not part of this form",
            )

    # Create evaluation
    create_dto = CreateEvaluationDTO(
        evaluation_type_id=payload.type_id,
        organization_id=payload.org_id,
        filled_by_employee_id=payload.filler_id,
        evaluated_employee_id=payload.eval_id,
        criterion_set_id=payload.set_id,
        status="completed",
    )
    
    evaluation = await evaluation_service.create(create_dto)
    
    # Save answers
    total_criteria = len(request.answers)
    passed_criteria = 0
    boolean_count = 0
    
    for answer in request.answers:
        # Count boolean answers for score calculation
        if isinstance(answer.value, bool):
            boolean_count += 1
            if answer.value:
                passed_criteria += 1
        
        create_value_dto = CreateCriterionValueDTO(
            evaluation_id=evaluation.id,
            criterion_id=answer.criterion_id,
            value=answer.value,
            notes=answer.comment,
        )
        await criterion_value_repo.create(create_value_dto)
    
    # Calculate score
    failed_criteria = boolean_count - passed_criteria
    score_percentage = (passed_criteria / boolean_count * 100) if boolean_count > 0 else 0.0
    
    # Update evaluation with stats
    update_dto = UpdateEvaluationDTO(
        total_criteria=total_criteria,
        passed_criteria=passed_criteria,
        failed_criteria=failed_criteria,
        score_percentage=score_percentage,
        comment=request.comment,
    )
    await evaluation_service.update(evaluation.id, update_dto)
    
    # Mark token as used
    mark_token_used(token)
    
    # Send export options to user via bot
    await _send_export_options(
        employee_service=employee_service,
        filler_id=payload.filler_id,
        evaluation_id=evaluation.id,
        score_percentage=score_percentage,
    )
    
    return SubmitResponse(
        evaluation_id=evaluation.id,
        score_percentage=score_percentage,
        passed_criteria=passed_criteria,
        failed_criteria=failed_criteria,
        total_criteria=total_criteria,
        boolean_criteria_count=boolean_count,
    )


@router.post("/token", response_model=CreateTokenResponse, dependencies=[Depends(_require_internal_key)])
async def create_token(request: CreateTokenRequest):
    """Create encrypted form token (called by bot internally).

    Protected by X-Internal-Key header. Set INTERNAL_API_KEY in env.
    """
    token = create_encrypted_token(
        organization_id=request.organization_id,
        criterion_set_id=request.criterion_set_id,
        filled_by_employee_id=request.filled_by_employee_id,
        evaluated_employee_id=request.evaluated_employee_id,
        evaluation_type_id=request.evaluation_type_id,
    )
    
    url = f"{config.WEBAPP_BASE_URL}?token={token}"
    
    return CreateTokenResponse(token=token, url=url)


# ==================== Generic Page Token ====================

class PageTokenPayload(BaseModel):
    """Generic page token payload."""
    page: str
    org_id: int
    user_telegram_id: int
    extra: dict = {}
    exp: int
    nonce: str


class CreatePageTokenRequest(BaseModel):
    """Request to create a page token."""
    page: str  # employees, evaluations, analytics, criteria_select
    organization_id: int
    user_telegram_id: int
    extra: dict = {}


def create_page_token(page: str, org_id: int, user_telegram_id: int, extra: dict | None = None) -> str:
    """Create encrypted token for any page type."""
    expiry = int(time.time()) + config.WEBAPP_TOKEN_EXPIRY
    nonce_bytes = os.urandom(12)

    payload = PageTokenPayload(
        page=page,
        org_id=org_id,
        user_telegram_id=user_telegram_id,
        extra=extra or {},
        exp=expiry,
        nonce=base64.b64encode(nonce_bytes).decode(),
    )

    cipher = _get_cipher()
    plaintext = payload.model_dump_json().encode()
    ciphertext = cipher.encrypt(nonce_bytes, plaintext, None)
    token_bytes = nonce_bytes + ciphertext
    return base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")


def decrypt_page_token(token: str) -> Optional[PageTokenPayload]:
    """Decrypt and validate a page token."""
    try:
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        token_bytes = base64.urlsafe_b64decode(token)
        if len(token_bytes) < 12:
            return None
        nonce_bytes = token_bytes[:12]
        ciphertext = token_bytes[12:]
        cipher = _get_cipher()
        plaintext = cipher.decrypt(nonce_bytes, ciphertext, None)
        payload = PageTokenPayload.model_validate_json(plaintext)
        if payload.exp < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _validate_page_token(token: str, expected_page: str) -> PageTokenPayload:
    """Decrypt, validate, and check page type."""
    payload = decrypt_page_token(token)
    if not payload:
        raise HTTPException(status_code=404, detail="Токен недействителен или истёк")
    if payload.page != expected_page:
        raise HTTPException(status_code=400, detail="Неверный тип страницы")
    return payload


@router.post("/page-token", dependencies=[Depends(_require_internal_key)])
async def create_page_token_endpoint(request: CreatePageTokenRequest):
    """Create encrypted page token (called by bot). Protected by X-Internal-Key header."""
    token = create_page_token(
        page=request.page,
        org_id=request.organization_id,
        user_telegram_id=request.user_telegram_id,
        extra=request.extra,
    )
    page_query = {
        "employees": "employees",
        "evaluations": "evaluations",
        "analytics": "analytics",
        "criteria_select": "criteria-select",
    }.get(request.page, request.page)

    url = f"{config.WEBAPP_BASE_URL}/?page={page_query}&token={token}"
    return {"token": token, "url": url}


# ==================== Employees Page ====================

ROLE_MAP = {
    1: {"id": 1, "name": "Сотрудник", "code": "employee"},
    2: {"id": 2, "name": "Менеджер", "code": "manager"},
    3: {"id": 3, "name": "Администратор", "code": "administrator"},
}


def _is_superuser_token(payload: "PageTokenPayload") -> bool:
    """Return True if the token belongs to a bot-level superuser."""
    return payload.user_telegram_id in config.TGBOT_ADMIN_IDS


@router.get("/employees/{token}")
async def get_employees_page(
    token: str,
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Get employee list for the employees page."""
    payload = _validate_page_token(token, "employees")

    is_superuser = _is_superuser_token(payload)
    all_orgs_mode = is_superuser and payload.org_id == 0

    if all_orgs_mode:
        org_name = "Все организации"
        employees_raw = await employee_service.get_all()
        all_orgs = await organization_service.get_all()
        org_name_map = {o.id: o.name for o in all_orgs}
    else:
        organization = await organization_service.get_by_id(payload.org_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Организация не найдена")
        org_name = organization.name
        org_name_map = {organization.id: organization.name}
        employees_raw = await employee_service.get_by_organization_id(payload.org_id)

    employees = [e for e in employees_raw if e.deleted_at is None]

    return {
        "employees": [
            {
                "id": e.id,
                "full_name": e.full_name,
                "position": e.position,
                "phone": e.phone,
                "employee_type_id": e.employee_type_id,
                "employee_type_name": ROLE_MAP.get(e.employee_type_id, {}).get("name", "—"),
                "is_active": e.is_active,
                "organization_name": org_name_map.get(e.organization_id, "—") if all_orgs_mode else None,
            }
            for e in employees
        ],
        "organization_name": org_name,
        "roles": list(ROLE_MAP.values()),
        "is_superuser": is_superuser,
        "all_orgs_mode": all_orgs_mode,
    }


@router.post("/employees/{token}/role")
async def update_employee_role_endpoint(
    token: str,
    request: dict,
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """Update employee role via the webapp."""
    payload = _validate_page_token(token, "employees")

    employee_id = request.get("employee_id")
    employee_type_id = request.get("employee_type_id")
    if not employee_id or not employee_type_id:
        raise HTTPException(status_code=400, detail="employee_id and employee_type_id required")

    # Verify the target employee belongs to the organisation encoded in the token.
    target = await employee_service.get_by_id(int(employee_id))
    if not target:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    is_superuser = _is_superuser_token(payload)
    if not is_superuser and target.organization_id != payload.org_id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    update_dto = UpdateEmployeeDTO(employee_type_id=int(employee_type_id))
    updated = await employee_service.update(int(employee_id), update_dto)
    if not updated:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    return {"ok": True, "employee_id": updated.id}


# ==================== My Evaluations Page ====================

@router.get("/evaluations/{token}")
async def get_evaluations_page(
    token: str,
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    evaluation_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Get evaluations for the current user."""
    payload = _validate_page_token(token, "evaluations")

    is_superuser = _is_superuser_token(payload)
    all_orgs_mode = is_superuser and payload.org_id == 0

    if all_orgs_mode:
        org_name = "Все организации"
        all_orgs = await organization_service.get_all()
        org_name_map = {o.id: o.name for o in all_orgs}
    else:
        organization = await organization_service.get_by_id(payload.org_id)
        org_name = organization.name if organization else "—"
        org_name_map = {organization.id: organization.name} if organization else {}

    employee_id = payload.extra.get("employee_id")
    employee_name = None
    evaluations = []

    # Superuser in all_orgs_mode sees all evaluations (optionally filtered by employee)
    if all_orgs_mode and not employee_id:
        evaluations_raw = await evaluation_service.get_all()
    elif employee_id:
        emp = await employee_service.get_by_id(int(employee_id))
        if emp:
            employee_name = emp.full_name
        evaluations_raw = await evaluation_service.get_by_employee_id(int(employee_id))
    else:
        evaluations_raw = []

    eval_types_cache: dict[int, str] = {}
    emp_name_cache: dict[int, str] = {}

    for ev in evaluations_raw:
        type_name = eval_types_cache.get(ev.evaluation_type_id)
        if type_name is None:
            et = await evaluation_type_service.get_by_id(ev.evaluation_type_id)
            type_name = et.name if et else "—"
            eval_types_cache[ev.evaluation_type_id] = type_name

        async def _get_emp_name(eid: int | None) -> str | None:
            if not eid:
                return None
            if eid in emp_name_cache:
                return emp_name_cache[eid]
            e = await employee_service.get_by_id(eid)
            name = e.full_name if e else None
            emp_name_cache[eid] = name  # type: ignore[assignment]
            return name

        evaluated_name = await _get_emp_name(ev.evaluated_employee_id)
        filler_name = await _get_emp_name(ev.filled_by_employee_id)

        evaluations.append({
            "id": ev.id,
            "evaluation_date": ev.evaluation_date.strftime("%d.%m.%Y") if ev.evaluation_date else None,
            "score_percentage": ev.score_percentage,
            "status": ev.status,
            "evaluation_type_name": type_name,
            "evaluated_employee_name": evaluated_name,
            "filled_by_employee_name": filler_name,
            "total_criteria": ev.total_criteria,
            "passed_criteria": ev.passed_criteria,
            "organization_name": org_name_map.get(ev.organization_id, "—") if all_orgs_mode else None,
        })

    return {
        "evaluations": evaluations,
        "organization_name": org_name,
        "employee_name": employee_name,
        "is_superuser": is_superuser,
        "all_orgs_mode": all_orgs_mode,
    }


# ==================== Analytics Page ====================

@router.get("/analytics/{token}")
async def get_analytics_page(
    token: str,
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    organization_service: OrganizationService = Depends(get_organization_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_value_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    """Get analytics data for the analytics page."""
    payload = _validate_page_token(token, "analytics")

    is_superuser = _is_superuser_token(payload)
    all_orgs_mode = is_superuser and payload.org_id == 0

    if all_orgs_mode:
        org_name = "Все организации"
        evaluations_raw = await evaluation_service.get_all()
    else:
        organization = await organization_service.get_by_id(payload.org_id)
        org_name = organization.name if organization else "—"
        evaluations_raw = await evaluation_service.get_by_organization_id(payload.org_id)

    evaluations = [e for e in evaluations_raw if e.deleted_at is None]

    total_evaluations = len(evaluations)
    avg_score = 0.0
    if total_evaluations > 0:
        scores = [e.score_percentage for e in evaluations if e.score_percentage is not None]
        avg_score = sum(scores) / len(scores) if scores else 0.0

    # --- Criteria stats: aggregate pass/fail per criterion ---
    # Value can be bool, int, float, str, or raw value_json (dict/JSON str) from DB
    def _is_passed(val):  # -> Optional[bool]
        if val is None:
            return None
        if isinstance(val, dict):
            v = val.get("value") or val.get("Value")
            if v is None:
                return None
            if val.get("type") == "boolean":
                return bool(v)
            return None
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "1", "yes", "да"):
                return True
            if s in ("false", "0", "no", "нет"):
                return False
            if s.startswith("{"):
                try:
                    import json
                    return _is_passed(json.loads(val))
                except (TypeError, ValueError):
                    return None
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        return None

    criteria_agg: dict[int, dict] = {}
    for ev in evaluations:
        values = await criterion_value_repo.get_by_evaluation_id(ev.id)
        for cv in values:
            if cv.criterion_id not in criteria_agg:
                criteria_agg[cv.criterion_id] = {"passed": 0, "failed": 0}
            passed = _is_passed(cv.value)
            if passed is not None:
                if passed:
                    criteria_agg[cv.criterion_id]["passed"] += 1
                else:
                    criteria_agg[cv.criterion_id]["failed"] += 1

    criteria_stats = []
    if criteria_agg:
        if all_orgs_mode:
            all_criteria = await criterion_service.get_all()
        else:
            all_criteria = await criterion_service.get_by_organization_id(payload.org_id)
        criteria_name_map = {c.id: c.name for c in all_criteria}

        for cid, stats in criteria_agg.items():
            total_checks = stats["passed"] + stats["failed"]
            if total_checks == 0:
                continue
            criteria_stats.append({
                "criterion_name": criteria_name_map.get(cid, f"#{cid}"),
                "total_checks": total_checks,
                "passed": stats["passed"],
                "failed": stats["failed"],
                "pass_rate": round(stats["passed"] / total_checks * 100, 1),
            })
        criteria_stats.sort(key=lambda x: x["pass_rate"])

    # --- Employee scores ---
    employee_map: dict[int, dict] = {}
    for ev in evaluations:
        eid = ev.evaluated_employee_id or ev.filled_by_employee_id
        if eid:
            if eid not in employee_map:
                emp = await employee_service.get_by_id(eid)
                employee_map[eid] = {
                    "employee_name": emp.full_name if emp else f"#{eid}",
                    "scores": [],
                }
            if ev.score_percentage is not None:
                employee_map[eid]["scores"].append(ev.score_percentage)

    employee_scores = []
    for info in employee_map.values():
        scores = info["scores"]
        employee_scores.append({
            "employee_name": info["employee_name"],
            "evaluations_count": len(scores),
            "average_score": sum(scores) / len(scores) if scores else 0.0,
        })
    employee_scores.sort(key=lambda x: x["average_score"], reverse=True)

    return {
        "organization_name": org_name,
        "period": payload.extra.get("period"),
        "criteria_stats": criteria_stats,
        "total_evaluations": total_evaluations,
        "average_score": round(avg_score, 1),
        "employee_scores": employee_scores,
        "is_superuser": is_superuser,
        "all_orgs_mode": all_orgs_mode,
    }


# ==================== Criteria Selection Page ====================

@router.get("/criteria-select/{token}")
async def get_criteria_select_page(
    token: str,
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    organization_service: OrganizationService = Depends(get_organization_service),
):
    """Get criteria list for multi-select page."""
    payload = _validate_page_token(token, "criteria_select")

    organization = await organization_service.get_by_id(payload.org_id)
    org_name = organization.name if organization else "—"

    set_id = payload.extra.get("criterion_set_id")
    set_name = None
    selected_ids: set[int] = set()

    if set_id:
        crit_set = await criterion_set_service.get_by_id(int(set_id))
        if crit_set:
            set_name = crit_set.name
            selected_ids = set(crit_set.criterion_ids or [])

    criteria_raw = await criterion_service.get_by_organization_id(payload.org_id)
    criteria = [c for c in criteria_raw if c.deleted_at is None]

    return {
        "criteria": [
            {
                "id": c.id,
                "name": c.name,
                "code": c.code,
                "description": c.description,
                "selected": c.id in selected_ids,
            }
            for c in criteria
        ],
        "organization_name": org_name,
        "criterion_set_name": set_name,
        "criterion_set_id": set_id,
    }


@router.post("/criteria-select/{token}/submit")
async def submit_criteria_select(
    token: str,
    request: dict,
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Save selected criteria for a criterion set."""
    from app.infra.database.repository.criterion_set.dto import UpdateCriterionSetDTO

    payload = _validate_page_token(token, "criteria_select")

    set_id = payload.extra.get("criterion_set_id")
    if not set_id:
        raise HTTPException(status_code=400, detail="criterion_set_id missing from token")

    # Verify the criterion set belongs to the organisation from the token.
    crit_set = await criterion_set_service.get_by_id(int(set_id))
    if not crit_set:
        raise HTTPException(status_code=404, detail="Набор критериев не найден")
    if crit_set.organization_id != payload.org_id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    criterion_ids = request.get("criterion_ids", [])
    if not isinstance(criterion_ids, list):
        raise HTTPException(status_code=400, detail="criterion_ids must be a list")

    update_dto = UpdateCriterionSetDTO(criterion_ids=[int(cid) for cid in criterion_ids])
    await criterion_set_service.update(int(set_id), update_dto)

    return {"ok": True}
