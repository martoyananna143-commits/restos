"""Shared helpers for web data routers."""

import json
import logging
import re
from typing import Optional

from fastapi import HTTPException

from .schemas import CriterionSetOut

logger = logging.getLogger(__name__)

def _criterion_set_out(s) -> CriterionSetOut:
    return CriterionSetOut(
        id=s.id,
        name=s.name,
        description=getattr(s, "description", None),
        is_default=s.is_default,
        criterion_ids=s.criterion_ids or [],
        source_type=getattr(s, "source_type", None) or "internal",
        source_url=getattr(s, "source_url", None),
        source_meta=getattr(s, "source_meta", None) or {},
    )
# ── Helpers ──────────────────────────────────────────────────────────────────

_HIDDEN_WEB_AI_MESSAGES = {
    "Кто ты? Представься.",
    (
        "Привет! Я — ассистент Restos, созданный для помощи пользователям "
        "системы Restos. Я помогу вам с анализом данных замеров, "
        "критериев и сотрудников, а также отвечу на любые вопросы. "
        "Чем могу помочь?"
    ),
}
_AI_FETCH_ALLOWED_ENTITIES = {
    "employees",
    "evaluations",
    "criteria",
    "criterion_sets",
    "evaluation_types",
    "organization",
    "analytics_summary",
}
_AI_FETCH_MAX_COMMANDS = 4
_AI_FETCH_DEFAULT_LIMIT = 30
_AI_FETCH_MAX_LIMIT = 120
_AI_FETCH_COMMAND_RE = re.compile(r"\[\[SYS_FETCH\s+(\{[\s\S]*?\})\s*\]\]")

def _require_same_org(current_emp, target_org_id: int):
    if current_emp.organization_id != target_org_id:
        raise HTTPException(status_code=403, detail="Access denied")


def _require_admin(emp, employee_types: list[dict]):
    my_type = next((t for t in employee_types if t["id"] == emp.employee_type_id), {})
    if not my_type.get("is_administrator", False):
        raise HTTPException(status_code=403, detail="Admin access required")


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


def _is_org_creator(emp, org, org_employees: list, employee_types: list[dict]) -> bool:
    """Check whether employee is organization creator.

    Source of truth:
    1) organization.meta["created_by_employee_id"] if present;
    2) fallback for legacy orgs: earliest admin employee in the org.
    """
    meta = _normalize_meta(getattr(org, "meta", {}))
    creator_id = meta.get("created_by_employee_id")
    if creator_id is not None:
        return int(creator_id) == int(emp.id)

    admin_type_ids = {
        int(t["id"]) for t in employee_types if bool(t.get("is_administrator", False))
    }
    admin_employees = [e for e in org_employees if int(e.employee_type_id) in admin_type_ids]
    if not admin_employees:
        return False

    # Legacy fallback: first created admin is treated as org creator.
    first_admin = min(admin_employees, key=lambda e: e.created_at)
    return int(first_admin.id) == int(emp.id)


def _extract_staff_profile_tag(raw: str) -> Optional[str]:
    """Best-effort role tag extracted from evaluation/set names/codes."""
    text = (raw or "").strip().lower()
    if not text:
        return None

    if any(token in text for token in ("хостес", "hostess", "hostes")):
        return "hostess"
    if any(token in text for token in ("официант", "waiter", "server")):
        return "waiter"
    if any(token in text for token in ("бармен", "bartender", "bar")):
        return "bartender"
    return None


def _validate_type_and_set_compatibility(eval_type, crit_set) -> None:
    """Reject obviously mismatched pairs like hostes + waiter."""
    eval_tag = _extract_staff_profile_tag(
        f"{getattr(eval_type, 'name', '')} {getattr(eval_type, 'code', '')}"
    )
    set_tag = _extract_staff_profile_tag(getattr(crit_set, "name", ""))

    if eval_tag and set_tag and eval_tag != set_tag:
        raise HTTPException(
            status_code=400,
            detail=(
                "Evaluation type and criterion set look incompatible. "
                "Select matching role-specific pair."
            ),
        )


def _is_employee_role(emp, employee_types: list[dict]) -> bool:
    """True only for regular 'employee' role (not managers/admins)."""
    my_type = next((t for t in employee_types if t["id"] == emp.employee_type_id), {})
    code = str(my_type.get("code", "")).strip().lower()
    return code == "employee"


def _can_view_own_or_related_evaluation(emp, evaluation) -> bool:
    """Employees can only see evaluations where they are filler or target."""
    return (
        getattr(evaluation, "filled_by_employee_id", None) == emp.id
        or getattr(evaluation, "evaluated_employee_id", None) == emp.id
    )


def _build_invite_url(code: str) -> str:
    from app.settings import config

    base = (getattr(config, "WEBAPP_BASE_URL", "") or "").strip().rstrip("/")
    if base:
        return f"{base}/?invite_code={code}&auth=register"
    return f"?invite_code={code}&auth=register"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_\s-]", "", text or "").strip().lower()
    cleaned = cleaned.replace("ё", "е")
    cleaned = re.sub(r"[\s-]+", "_", cleaned)
    return cleaned[:48] or "criterion"


def _normalize_value_type(raw: str) -> str:
    value = (raw or "").strip().lower()
    mapping = {
        "bool": "boolean",
        "boolean": "boolean",
        "да/нет": "boolean",
        "yes_no": "boolean",
        "num": "number",
        "number": "number",
        "numeric": "number",
        "int": "number",
        "float": "number",
        "str": "string",
        "string": "string",
        "text": "string",
        "текст": "string",
    }
    return mapping.get(value, "boolean")


def _extract_json_payload(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {"criteria": data}
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return {"criteria": data}
        except Exception:
            pass

    return {}

