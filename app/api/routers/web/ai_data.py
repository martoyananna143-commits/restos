"""Web data routes: AI assistant."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_ai_assistant_service,
    get_criterion_service,
    get_criterion_set_service,
    get_employee_service,
    get_evaluation_service,
    get_evaluation_type_service,
    get_organization_service,
)
from app.api.routers.web_auth import get_current_web_employee_pin_fresh
from app.internal.services.ai_assistant_service import AIAssistantService
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.organization_service import OrganizationService
from .ai_helpers import (
    _build_ai_data_context,
    _clean_web_ai_history,
    _run_ai_chat_with_dynamic_data,
    _run_ai_request_with_bot_fallback,
)
from .helpers import _extract_json_payload, _normalize_value_type, _require_admin, _slugify
from .schemas import (
    AIChatIn,
    AIChatOut,
    AIConfirmCriterionSetIn,
    AICreateCriterionSetIn,
    AICreateCriterionSetOut,
    AIMessageOut,
    AIPreviewCriterionSetIn,
    AIPreviewCriterionSetOut,
)

router = APIRouter()

@router.post("/ai/chat", response_model=AIChatOut)
async def ai_chat(
    data: AIChatIn,
    emp=Depends(get_current_web_employee_pin_fresh),
    ai_assistant_service: AIAssistantService = Depends(get_ai_assistant_service),
    organization_service: OrganizationService = Depends(get_organization_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    evaluation_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    user_message = (data.message or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is required")

    data_context = await _build_ai_data_context(
        emp.organization_id,
        criterion_service,
        criterion_set_service,
        evaluation_type_service,
    )
    if data.mode == "criteria_sets":
        data_context += (
            "\n\nРежим: помощь по критериям и наборам. "
            "Предлагай практичные критерии для оценки персонала."
        )

    safe_history = _clean_web_ai_history(
        [
            {"role": m.role, "content": m.content}
            for m in data.conversation_history[-30:]
            if m.role in ("system", "user", "assistant") and (m.content or "").strip()
        ]
    )

    result = await _run_ai_chat_with_dynamic_data(
        ai_assistant_service=ai_assistant_service,
        organization_id=emp.organization_id,
        user_id=emp.id,
        user_message=user_message,
        safe_history=safe_history,
        base_data_context=data_context,
        organization_service=organization_service,
        employee_service=employee_service,
        evaluation_service=evaluation_service,
        criterion_service=criterion_service,
        criterion_set_service=criterion_set_service,
        evaluation_type_service=evaluation_type_service,
    )
    if not result.get("success"):
        error_text = result.get("response", "❌ Не удалось получить ответ от AI. Попробуйте позже.")
        fallback_history = list(safe_history)
        fallback_history.append({"role": "user", "content": user_message})
        fallback_history.append({"role": "assistant", "content": error_text})
        out_history = [
            AIMessageOut(role=item.get("role", "assistant"), content=item.get("content", ""))
            for item in _clean_web_ai_history(fallback_history)
        ]
        return AIChatOut(response=error_text, conversation_history=out_history)

    history = _clean_web_ai_history(result.get("conversation_history", []))
    out_history = [
        AIMessageOut(role=item.get("role", "assistant"), content=item.get("content", ""))
        for item in history
    ]
    return AIChatOut(response=result.get("response", ""), conversation_history=out_history)


@router.post("/criterion-sets/ai-create", response_model=AICreateCriterionSetOut, status_code=status.HTTP_201_CREATED)
async def create_criterion_set_with_ai(
    data: AICreateCriterionSetIn,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    ai_assistant_service: AIAssistantService = Depends(get_ai_assistant_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    evaluation_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    prompt = (data.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    data_context = await _build_ai_data_context(
        emp.organization_id,
        criterion_service,
        criterion_set_service,
        evaluation_type_service,
    )
    ai_prompt = (
        "Сформируй набор критериев для оценки персонала.\n"
        "Верни строго JSON без markdown и без пояснений.\n"
        "Формат:\n"
        "{\n"
        '  "set_name": "Название",\n'
        '  "description": "Описание",\n'
        '  "criteria": [\n'
        '    {"name":"...", "value_type":"boolean|number|string", "description":"...", "is_required":true}\n'
        "  ]\n"
        "}\n\n"
        f"Запрос пользователя: {prompt}\n"
        f"Название набора (если задано): {data.set_name or 'не задано'}\n"
        f"Описание набора (если задано): {data.description or 'не задано'}"
    )

    ai_result = await _run_ai_request_with_bot_fallback(
        ai_assistant_service,
        user_id=emp.id,
        chat_id=emp.organization_id,
        user_text=ai_prompt,
        conversation_history=[],
        data_context=data_context,
    )
    if not ai_result.get("success"):
        raise HTTPException(status_code=502, detail=ai_result.get("response", "AI temporarily unavailable"))

    ai_response = ai_result.get("response", "")
    payload = _extract_json_payload(ai_response)
    criteria_raw = payload.get("criteria")
    if not isinstance(criteria_raw, list):
        raise HTTPException(status_code=422, detail="AI did not return valid criteria JSON")

    normalized_criteria: list[dict] = []
    for item in criteria_raw[:60]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        normalized_criteria.append(
            {
                "name": name[:120],
                "value_type": _normalize_value_type(str(item.get("value_type", "boolean"))),
                "description": str(item.get("description", "")).strip()[:500] or None,
                "is_required": bool(item.get("is_required", True)),
            }
        )

    if not normalized_criteria:
        raise HTTPException(status_code=422, detail="AI returned empty criteria list")

    set_name = (data.set_name or payload.get("set_name") or f"AI набор {datetime.now().strftime('%d.%m')}").strip()
    set_description = (data.description or payload.get("description") or "").strip() or None

    from app.infra.database.repository.criterion.dto import CreateCriterionDTO
    from app.infra.database.repository.criterion_set.dto import CreateCriterionSetDTO

    existing_criteria = await criterion_service.get_by_organization_id(emp.organization_id)
    used_codes = {c.code for c in existing_criteria}
    sort_order = max([getattr(c, "sort_order", 0) for c in existing_criteria], default=0) + 1

    created_ids: list[int] = []
    for idx, criterion in enumerate(normalized_criteria, start=1):
        base_code = _slugify(criterion["name"])
        code = base_code
        suffix = 2
        while code in used_codes:
            code = f"{base_code}_{suffix}"
            suffix += 1
        used_codes.add(code)

        dto = CreateCriterionDTO(
            organization_id=emp.organization_id,
            name=criterion["name"],
            code=code,
            description=criterion["description"],
            value_type=criterion["value_type"],
            is_required=criterion["is_required"],
            sort_order=sort_order + idx,
        )
        created = await criterion_service.create(dto)
        created_ids.append(created.id)

    created_set = await criterion_set_service.create(
        CreateCriterionSetDTO(
            organization_id=emp.organization_id,
            name=set_name[:120],
            description=set_description,
            is_default=data.is_default,
            criterion_ids=created_ids,
        )
    )

    return AICreateCriterionSetOut(
        set_id=created_set.id,
        set_name=created_set.name,
        criteria_created=len(created_ids),
        criterion_ids=created_ids,
        ai_response=ai_response,
    )


@router.post("/criterion-sets/ai-preview", response_model=AIPreviewCriterionSetOut)
async def preview_criterion_set_with_ai(
    data: AIPreviewCriterionSetIn,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    ai_assistant_service: AIAssistantService = Depends(get_ai_assistant_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    evaluation_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    """Step 1 of two-step AI flow: generate criteria WITHOUT saving to DB.

    Returns the parsed criteria list for user review/editing before confirm.
    """
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    prompt = (data.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    data_context = await _build_ai_data_context(
        emp.organization_id,
        criterion_service,
        criterion_set_service,
        evaluation_type_service,
    )
    ai_prompt = (
        "Сформируй набор критериев для оценки персонала.\n"
        "Верни строго JSON без markdown и без пояснений.\n"
        "Формат:\n"
        "{\n"
        '  "set_name": "Название",\n'
        '  "description": "Описание",\n'
        '  "criteria": [\n'
        '    {"name":"...", "value_type":"boolean|number|string", "description":"...", "is_required":true}\n'
        "  ]\n"
        "}\n\n"
        f"Запрос пользователя: {prompt}\n"
        f"Название набора (если задано): {data.set_name or 'не задано'}\n"
        f"Описание набора (если задано): {data.description or 'не задано'}"
    )

    ai_result = await _run_ai_request_with_bot_fallback(
        ai_assistant_service,
        user_id=emp.id,
        chat_id=emp.organization_id,
        user_text=ai_prompt,
        conversation_history=[],
        data_context=data_context,
    )
    if not ai_result.get("success"):
        raise HTTPException(status_code=502, detail=ai_result.get("response", "AI temporarily unavailable"))

    ai_response = ai_result.get("response", "")
    payload = _extract_json_payload(ai_response)
    criteria_raw = payload.get("criteria")
    if not isinstance(criteria_raw, list):
        raise HTTPException(status_code=422, detail="AI did not return valid criteria JSON")

    normalized: list[AICriterionPreviewItem] = []
    for item in criteria_raw[:60]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        normalized.append(AICriterionPreviewItem(
            name=name[:120],
            value_type=_normalize_value_type(str(item.get("value_type", "boolean"))),
            description=str(item.get("description", "")).strip()[:500] or None,
            is_required=bool(item.get("is_required", True)),
        ))

    if not normalized:
        raise HTTPException(status_code=422, detail="AI returned empty criteria list")

    set_name = (data.set_name or payload.get("set_name") or f"AI набор {datetime.now().strftime('%d.%m')}").strip()
    set_description = (data.description or payload.get("description") or "").strip() or None

    return AIPreviewCriterionSetOut(
        set_name=set_name,
        description=set_description,
        criteria=normalized,
        ai_response=ai_response,
    )


@router.post("/criterion-sets/ai-confirm", response_model=AICreateCriterionSetOut, status_code=status.HTTP_201_CREATED)
async def confirm_criterion_set_from_preview(
    data: AIConfirmCriterionSetIn,
    emp=Depends(get_current_web_employee_pin_fresh),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
):
    """Step 2 of two-step AI flow: save user-edited criteria to DB."""
    emp_types = await employee_service.get_employee_types()
    _require_admin(emp, emp_types)

    if not data.criteria:
        raise HTTPException(status_code=400, detail="criteria list is empty")

    from app.infra.database.repository.criterion.dto import CreateCriterionDTO
    from app.infra.database.repository.criterion_set.dto import CreateCriterionSetDTO

    existing_criteria = await criterion_service.get_by_organization_id(emp.organization_id)
    used_codes = {c.code for c in existing_criteria}
    sort_order = max([getattr(c, "sort_order", 0) for c in existing_criteria], default=0) + 1

    created_ids: list[int] = []
    for idx, criterion in enumerate(data.criteria[:60], start=1):
        name = criterion.name.strip()[:120]
        if not name:
            continue
        base_code = _slugify(name)
        code = base_code
        suffix = 2
        while code in used_codes:
            code = f"{base_code}_{suffix}"
            suffix += 1
        used_codes.add(code)

        dto = CreateCriterionDTO(
            organization_id=emp.organization_id,
            name=name,
            code=code,
            description=criterion.description,
            value_type=_normalize_value_type(criterion.value_type),
            is_required=criterion.is_required,
            sort_order=sort_order + idx,
        )
        created = await criterion_service.create(dto)
        created_ids.append(created.id)

    if not created_ids:
        raise HTTPException(status_code=422, detail="No valid criteria to save")

    set_name = data.set_name.strip()[:120] or f"AI набор {datetime.now().strftime('%d.%m')}"
    set_description = (data.description or "").strip() or None

    created_set = await criterion_set_service.create(
        CreateCriterionSetDTO(
            organization_id=emp.organization_id,
            name=set_name,
            description=set_description,
            is_default=data.is_default,
            criterion_ids=created_ids,
        )
    )

    return AICreateCriterionSetOut(
        set_id=created_set.id,
        set_name=created_set.name,
        criteria_created=len(created_ids),
        criterion_ids=created_ids,
        ai_response="",
    )
