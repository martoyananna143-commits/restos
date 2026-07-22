"""AI-specific helpers for web data routers."""

import json
import logging
import re
from typing import Optional

from app.internal.services.ai_assistant_service import AIAssistantService
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.organization_service import OrganizationService
from .helpers import (
    _AI_FETCH_ALLOWED_ENTITIES,
    _AI_FETCH_COMMAND_RE,
    _AI_FETCH_DEFAULT_LIMIT,
    _AI_FETCH_MAX_COMMANDS,
    _AI_FETCH_MAX_LIMIT,
    _HIDDEN_WEB_AI_MESSAGES,
)

logger = logging.getLogger(__name__)

async def _build_ai_data_context(
    organization_id: int,
    criterion_service: CriterionService,
    criterion_set_service: CriterionSetService,
    evaluation_type_service: EvaluationTypeService,
) -> str:
    criteria = await criterion_service.get_by_organization_id(organization_id)
    sets = await criterion_set_service.get_by_organization_id(organization_id)
    eval_types = await evaluation_type_service.get_all(organization_id=organization_id)

    criteria_preview = ", ".join(c.name for c in criteria[:15]) if criteria else "нет"
    sets_preview = ", ".join(s.name for s in sets[:10]) if sets else "нет"
    eval_types_preview = ", ".join(t.name for t in eval_types[:8]) if eval_types else "нет"

    return (
        f"Организация ID: {organization_id}\n"
        f"Типов оценок: {len(eval_types)} ({eval_types_preview})\n"
        f"Наборов критериев: {len(sets)} ({sets_preview})\n"
        f"Критериев: {len(criteria)} ({criteria_preview})\n"
        "Используй только русский язык."
    )


async def _run_ai_request_with_bot_fallback(
    ai_assistant_service: AIAssistantService,
    *,
    user_id: int,
    chat_id: int,
    user_text: str,
    conversation_history: list[dict],
    data_context: str,
) -> dict:
    """Run AI request like bot flow: stream first, then non-stream fallback."""
    stream_error: Optional[str] = None

    try:
        async for stream_data in ai_assistant_service.process_ai_request_stream(
            user_id=user_id,
            chat_id=chat_id,
            user_text=user_text,
            conversation_history=conversation_history,
            data_context=data_context,
        ):
            if stream_data.get("error"):
                stream_error = str(stream_data.get("error", "stream_failed"))
                break

            if stream_data.get("completed"):
                full_text = stream_data.get("full_text", "") or ""
                updated_history = stream_data.get("conversation_history", conversation_history)
                return {
                    "success": True,
                    "response": full_text,
                    "conversation_history": updated_history,
                }
    except Exception as exc:
        stream_error = str(exc)
        logger.warning("AI stream phase failed, switching to fallback: %s", exc)

    if stream_error:
        logger.info("AI stream returned error: %s. Trying non-stream fallback.", stream_error)

    return await ai_assistant_service.process_ai_request(
        user_id=user_id,
        chat_id=chat_id,
        user_text=user_text,
        conversation_history=conversation_history,
        data_context=data_context,
    )


def _clean_web_ai_history(history: list[dict]) -> list[dict]:
    """Strip internal seed messages and remove adjacent duplicates for web UI."""
    cleaned: list[dict] = []
    last_role: Optional[str] = None
    last_content: Optional[str] = None

    for item in history:
        role = item.get("role", "")
        content = (item.get("content", "") or "").strip()
        if role not in ("user", "assistant"):
            continue
        if role == "assistant":
            content = _strip_ai_fetch_commands(content)
        if not content:
            continue
        if content in _HIDDEN_WEB_AI_MESSAGES:
            continue
        if role == last_role and content == last_content:
            continue
        cleaned.append({"role": role, "content": content})
        last_role = role
        last_content = content

    return cleaned


def _extract_ai_fetch_commands(text: str) -> list[dict]:
    """Extract and sanitize AI fetch commands from assistant output."""
    commands: list[dict] = []
    raw = text or ""
    for match in _AI_FETCH_COMMAND_RE.findall(raw):
        if len(commands) >= _AI_FETCH_MAX_COMMANDS:
            break
        try:
            payload = json.loads(match)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        entity = str(payload.get("entity", "")).strip().lower()
        if entity not in _AI_FETCH_ALLOWED_ENTITIES:
            continue
        try:
            limit_raw = payload.get("limit", _AI_FETCH_DEFAULT_LIMIT)
            limit = int(limit_raw)
        except Exception:
            limit = _AI_FETCH_DEFAULT_LIMIT
        limit = max(1, min(limit, _AI_FETCH_MAX_LIMIT))
        commands.append({"entity": entity, "limit": limit})
    return commands


def _strip_ai_fetch_commands(text: str) -> str:
    """Remove internal command blocks from model text before returning to UI."""
    cleaned = _AI_FETCH_COMMAND_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def _load_ai_fetch_payload(
    *,
    organization_id: int,
    commands: list[dict],
    organization_service: OrganizationService,
    employee_service: EmployeeService,
    evaluation_service: EvaluationService,
    criterion_service: CriterionService,
    criterion_set_service: CriterionSetService,
    evaluation_type_service: EvaluationTypeService,
) -> str:
    """Load compact, non-sensitive org-scoped data requested by AI commands."""
    chunks: list[str] = []
    for cmd in commands:
        entity = cmd["entity"]
        limit = cmd["limit"]

        if entity == "organization":
            org = await organization_service.get_by_id(organization_id)
            if not org:
                chunks.append("organization: not found")
                continue
            chunks.append(
                "organization:\n"
                + json.dumps(
                    {
                        "id": org.id,
                        "name": org.name,
                        "code": getattr(org, "code", None),
                        "is_active": getattr(org, "is_active", True),
                    },
                    ensure_ascii=False,
                )
            )
            continue

        if entity == "employees":
            rows = await employee_service.get_by_organization_id(organization_id)
            payload = [
                {
                    "id": e.id,
                    "full_name": e.full_name,
                    "position": e.position,
                    "employee_type_id": e.employee_type_id,
                    "is_active": e.is_active,
                    "hire_date": str(e.hire_date) if getattr(e, "hire_date", None) else None,
                }
                for e in rows[:limit]
            ]
            chunks.append(f"employees({len(payload)}):\n" + json.dumps(payload, ensure_ascii=False))
            continue

        if entity == "criteria":
            rows = await criterion_service.get_by_organization_id(organization_id)
            payload = [
                {
                    "id": c.id,
                    "name": c.name,
                    "code": c.code,
                    "value_type": getattr(c, "value_type", "boolean"),
                    "is_required": getattr(c, "is_required", True),
                    "is_active": getattr(c, "is_active", True),
                    "description": getattr(c, "description", None),
                }
                for c in rows[:limit]
            ]
            chunks.append(f"criteria({len(payload)}):\n" + json.dumps(payload, ensure_ascii=False))
            continue

        if entity == "criterion_sets":
            rows = await criterion_set_service.get_by_organization_id(organization_id)
            payload = [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": getattr(s, "description", None),
                    "is_default": s.is_default,
                    "criteria_count": len(s.criterion_ids or []),
                }
                for s in rows[:limit]
            ]
            chunks.append(f"criterion_sets({len(payload)}):\n" + json.dumps(payload, ensure_ascii=False))
            continue

        if entity == "evaluation_types":
            rows = await evaluation_type_service.get_all(organization_id=organization_id)
            payload = [
                {
                    "id": t.id,
                    "name": t.name,
                    "code": t.code,
                    "description": getattr(t, "description", None),
                }
                for t in rows[:limit]
            ]
            chunks.append(f"evaluation_types({len(payload)}):\n" + json.dumps(payload, ensure_ascii=False))
            continue

        if entity == "evaluations":
            rows = await evaluation_service.get_by_organization_id(organization_id)
            rows_sorted = sorted(rows, key=lambda x: str(getattr(x, "created_at", "")), reverse=True)
            payload = [
                {
                    "id": ev.id,
                    "created_at": str(getattr(ev, "created_at", "")) or None,
                    "evaluation_date": str(getattr(ev, "evaluation_date", "")) or None,
                    "evaluation_type_id": ev.evaluation_type_id,
                    "filled_by_employee_id": getattr(ev, "filled_by_employee_id", None),
                    "evaluated_employee_id": getattr(ev, "evaluated_employee_id", None),
                    "score_percentage": getattr(ev, "score_percentage", None),
                    "status": getattr(ev, "status", None),
                    "total_criteria": getattr(ev, "total_criteria", None),
                    "passed_criteria": getattr(ev, "passed_criteria", None),
                    "failed_criteria": getattr(ev, "failed_criteria", None),
                }
                for ev in rows_sorted[:limit]
            ]
            chunks.append(f"evaluations({len(payload)}):\n" + json.dumps(payload, ensure_ascii=False))
            continue

        if entity == "analytics_summary":
            rows = await evaluation_service.get_by_organization_id(organization_id)
            employees = await employee_service.get_by_organization_id(organization_id)
            scores = [
                getattr(ev, "score_percentage", None)
                for ev in rows
                if getattr(ev, "score_percentage", None) is not None
            ]
            payload = {
                "evaluations_total": len(rows),
                "employees_total": len(employees),
                "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            }
            chunks.append("analytics_summary:\n" + json.dumps(payload, ensure_ascii=False))

    return "\n\n".join(chunks)


async def _run_ai_chat_with_dynamic_data(
    *,
    ai_assistant_service: AIAssistantService,
    organization_id: int,
    user_id: int,
    user_message: str,
    safe_history: list[dict],
    base_data_context: str,
    organization_service: OrganizationService,
    employee_service: EmployeeService,
    evaluation_service: EvaluationService,
    criterion_service: CriterionService,
    criterion_set_service: CriterionSetService,
    evaluation_type_service: EvaluationTypeService,
) -> dict:
    """Execute AI chat with optional command-driven dynamic data loading."""
    history = list(safe_history)
    request_text = user_message
    data_context = base_data_context
    result: dict = {"success": False, "response": "", "conversation_history": history}

    for _ in range(3):
        result = await _run_ai_request_with_bot_fallback(
            ai_assistant_service,
            user_id=user_id,
            chat_id=organization_id,
            user_text=request_text,
            conversation_history=history,
            data_context=data_context,
        )
        if not result.get("success"):
            return result

        raw_response = result.get("response", "") or ""
        commands = _extract_ai_fetch_commands(raw_response)
        if not commands:
            result["response"] = _strip_ai_fetch_commands(raw_response)
            result["conversation_history"] = result.get("conversation_history", history)
            return result

        fetched_data = await _load_ai_fetch_payload(
            organization_id=organization_id,
            commands=commands,
            organization_service=organization_service,
            employee_service=employee_service,
            evaluation_service=evaluation_service,
            criterion_service=criterion_service,
            criterion_set_service=criterion_set_service,
            evaluation_type_service=evaluation_type_service,
        )
        if not fetched_data:
            result["response"] = _strip_ai_fetch_commands(raw_response)
            result["conversation_history"] = result.get("conversation_history", history)
            return result

        history = list(result.get("conversation_history", history))
        if history and history[-1].get("role") == "assistant":
            visible = _strip_ai_fetch_commands(history[-1].get("content", ""))
            history[-1]["content"] = visible or "Принял, загружаю данные и продолжаю."

        history.append(
            {
                "role": "system",
                "content": (
                    "Служебная подгрузка данных выполнена. "
                    "Данные только по текущей организации пользователя:\n"
                    f"{fetched_data}\n\n"
                    "Теперь дай финальный ответ пользователю. "
                    "Не показывай служебные команды."
                ),
            }
        )
        request_text = "Продолжи ответ с учетом загруженных данных."

    # Failsafe if model keeps requesting commands in a loop.
    result["response"] = _strip_ai_fetch_commands(result.get("response", ""))
    result["conversation_history"] = result.get("conversation_history", history)
    return result
