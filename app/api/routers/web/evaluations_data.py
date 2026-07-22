"""Web data routes: evaluations, exports, analytics."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_criterion_service,
    get_criterion_set_service,
    get_criterion_value_repository,
    get_employee_service,
    get_evaluation_service,
    get_evaluation_type_service,
    get_excel_report_service,
    get_google_criterion_sync_service,
    get_organization_service,
    get_pdf_report_service,
)
from app.api.routers.web_auth import get_current_web_employee_download, get_current_web_employee_pin_fresh
from app.infra.database.repository.criterion_value.dto import CreateCriterionValueDTO
from app.infra.database.repository.evaluation.dto import CreateEvaluationDTO, UpdateEvaluationDTO
from app.infra.database.repository.criterion_value.criterion_value_asyncpg import CriterionValueRepositoryAsyncpg
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.excel_report_service import ExcelReportService
from app.internal.services.google_criterion_sync_service import GoogleCriterionSyncService
from app.internal.services.google_sheet_service import GoogleSheetError
from app.internal.services.organization_service import OrganizationService
from app.internal.services.pdf_report_service import PDFReportService
from .helpers import _can_view_own_or_related_evaluation, _is_employee_role
from .schemas import *

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Evaluations ───────────────────────────────────────────────────────────────

@router.get("/evaluations", response_model=list[EvaluationOut])
async def list_evaluations(
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    eval_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
):
    evaluations = await evaluation_service.get_by_organization_id(emp.organization_id)
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        evaluations = [
            ev for ev in evaluations if _can_view_own_or_related_evaluation(emp, ev)
        ]

    # Build lookup caches
    eval_types = await eval_type_service.get_all(organization_id=emp.organization_id)
    type_map = {t.id: t.name for t in eval_types}

    all_employees = await employee_service.get_by_organization_id(emp.organization_id)
    emp_map = {e.id: e.full_name for e in all_employees}

    result = []
    for ev in evaluations:
        is_done = getattr(ev, "status", "") == "completed"
        score = float(ev.score_percentage) if is_done else None
        result.append(EvaluationOut(
            id=ev.id,
            evaluated_employee_id=getattr(ev, "evaluated_employee_id", None),
            evaluated_employee_name=emp_map.get(getattr(ev, "evaluated_employee_id", 0)),
            evaluation_type_id=ev.evaluation_type_id,
            evaluation_type_name=type_map.get(ev.evaluation_type_id),
            criterion_set_id=getattr(ev, "criterion_set_id", 0),
            score_percentage=score,
            status="completed" if is_done else "in_progress",
            created_at=str(ev.created_at),
        ))
    return result


@router.get("/evaluations/{evaluation_id}/detail", response_model=EvaluationDetailOut)
async def get_evaluation_detail(
    evaluation_id: int,
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    eval_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    org_service: OrganizationService = Depends(get_organization_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    """Full evaluation payload for UI (same facts as PDF/Excel export)."""
    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.organization_id != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types) and not _can_view_own_or_related_evaluation(
        emp, evaluation
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    data = await _build_export_data(
        evaluation_id,
        emp,
        evaluation_service,
        employee_service,
        criterion_service,
        criterion_set_service,
        eval_type_service,
        org_service,
        cv_repo,
    )
    is_done = getattr(evaluation, "status", "") == "completed"
    score = float(evaluation.score_percentage) if is_done else None
    status = "completed" if is_done else "in_progress"
    ev_comment = getattr(evaluation, "comment", None)
    crit_rows = [
        EvaluationCriterionAnswerOut(
            name=c["name"],
            value_type=c.get("value_type", "boolean"),
            value=c.get("value"),
            comment=c.get("comment") or "",
        )
        for c in data.get("criteria", [])
    ]
    return EvaluationDetailOut(
        evaluation_id=evaluation_id,
        organization_name=data["organization_name"],
        evaluation_type_name=data["evaluation_type_name"],
        criterion_set_name=data.get("criterion_set_name"),
        evaluated_employee_name=data["evaluated_employee_name"],
        filled_by_employee_name=data["filled_by_employee_name"],
        evaluation_date=data["evaluation_date"],
        score_percentage=score,
        passed_criteria=int(data.get("passed_criteria", 0) or 0),
        failed_criteria=int(data.get("failed_criteria", 0) or 0),
        total_criteria=int(data.get("total_criteria", 0) or 0),
        status=status,
        comment=ev_comment if ev_comment else None,
        criteria=crit_rows,
    )


@router.post("/evaluations/start", response_model=StartEvaluationResponse)
async def start_evaluation(
    data: StartEvaluationRequest,
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    eval_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    org_service: OrganizationService = Depends(get_organization_service),
    google_sync: GoogleCriterionSyncService = Depends(get_google_criterion_sync_service),
):
    """Start a new evaluation and return criteria to fill."""
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        raise HTTPException(status_code=403, detail="Employees cannot create evaluations")

    target_emp = await employee_service.get_by_id(data.evaluated_employee_id)
    if not target_emp or target_emp.organization_id != emp.organization_id:
        raise HTTPException(status_code=404, detail="Target employee not found")

    crit_set = await criterion_set_service.get_by_id(data.criterion_set_id)
    if not crit_set or crit_set.organization_id != emp.organization_id:
        raise HTTPException(status_code=404, detail="Criterion set not found")

    eval_type = await eval_type_service.get_by_id(data.evaluation_type_id)
    if not eval_type or eval_type.organization_id != emp.organization_id:
        raise HTTPException(status_code=404, detail="Evaluation type not found")

    org = await org_service.get_by_id(emp.organization_id)
    source_type = getattr(crit_set, "source_type", None) or "internal"
    if source_type != "internal":
        try:
            criterion_ids = await google_sync.sync_set(
                data.criterion_set_id,
                emp.organization_id,
                force=False,
            )
            crit_set = await criterion_set_service.get_by_id(data.criterion_set_id) or crit_set
        except GoogleSheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        criterion_ids = crit_set.criterion_ids or []
    criteria = await criterion_service.get_by_ids(criterion_ids)

    dto = CreateEvaluationDTO(
        organization_id=emp.organization_id,
        criterion_set_id=data.criterion_set_id,
        evaluation_type_id=data.evaluation_type_id,
        filled_by_employee_id=emp.id,
        evaluated_employee_id=data.evaluated_employee_id,
    )
    evaluation = await evaluation_service.create(dto)

    return StartEvaluationResponse(
        evaluation_id=evaluation.id,
        criteria=[
            CriterionOut(
                id=c.id,
                name=c.name,
                code=c.code,
                description=getattr(c, "description", None),
                value_type=getattr(c, "value_type", "boolean"),
                is_required=getattr(c, "is_required", True),
            )
            for c in criteria
        ],
        organization_name=org.name if org else "",
        evaluated_employee_name=target_emp.full_name,
        criterion_set_name=crit_set.name,
    )


async def _persist_web_evaluation_answers(
    evaluation_id: int,
    answers: list[AnswerIn],
    crit_map: dict,
    cv_repo: CriterionValueRepositoryAsyncpg,
) -> int:
    """Upsert criterion_values rows (ON CONFLICT upsert in repository)."""
    n = 0
    for answer in answers:
        crit = crit_map.get(answer.criterion_id)
        if not crit:
            continue
        value_type = getattr(crit, "value_type", "boolean")

        if value_type == "boolean":
            bool_val = (
                answer.value
                if isinstance(answer.value, bool)
                else str(answer.value).lower() in ("true", "1")
            )
            dto = CreateCriterionValueDTO(
                evaluation_id=evaluation_id,
                criterion_id=answer.criterion_id,
                value=bool_val,
                notes=answer.comment,
            )
        elif value_type == "number":
            try:
                if isinstance(answer.value, bool):
                    num = 0.0
                elif isinstance(answer.value, (int, float)):
                    num = float(answer.value)
                else:
                    num = float(answer.value)
            except (ValueError, TypeError):
                num = 0.0
            dto = CreateCriterionValueDTO(
                evaluation_id=evaluation_id,
                criterion_id=answer.criterion_id,
                value=num,
                notes=answer.comment,
            )
        else:
            text_val = str(answer.value).strip()
            dto = CreateCriterionValueDTO(
                evaluation_id=evaluation_id,
                criterion_id=answer.criterion_id,
                value=text_val,
                notes=answer.comment,
            )
        await cv_repo.create(dto)
        n += 1
    return n


@router.get("/evaluations/{evaluation_id}/resume", response_model=ResumeEvaluationResponse)
async def resume_evaluation(
    evaluation_id: int,
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    org_service: OrganizationService = Depends(get_organization_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    """Load a draft evaluation for the web form (criteria + saved answers)."""
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        raise HTTPException(status_code=403, detail="Employees cannot fill evaluations")

    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.organization_id != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if getattr(evaluation, "status", "") == "completed":
        raise HTTPException(status_code=400, detail="Evaluation is already completed")
    if evaluation.filled_by_employee_id != emp.id:
        raise HTTPException(status_code=403, detail="Only the evaluator can continue this draft")

    crit_set = await criterion_set_service.get_by_id(evaluation.criterion_set_id or 0)
    if not crit_set:
        raise HTTPException(status_code=404, detail="Criterion set not found")

    org = await org_service.get_by_id(emp.organization_id)
    target_emp = await employee_service.get_by_id(evaluation.evaluated_employee_id or 0)
    criterion_ids = crit_set.criterion_ids or []
    criteria = await criterion_service.get_by_ids(criterion_ids)

    cv_list = await cv_repo.get_by_evaluation_id(evaluation_id)
    saved_answers: list[AnswerIn] = []
    for cv in cv_list:
        v = cv.value
        if isinstance(v, bool):
            val: bool | float | str = v
        elif isinstance(v, (int, float)):
            val = float(v)
        else:
            val = str(v) if v is not None else ""
        saved_answers.append(
            AnswerIn(criterion_id=cv.criterion_id, value=val, comment=cv.notes)
        )

    return ResumeEvaluationResponse(
        evaluation_id=evaluation_id,
        criteria=[
            CriterionOut(
                id=c.id,
                name=c.name,
                code=c.code,
                description=getattr(c, "description", None),
                value_type=getattr(c, "value_type", "boolean"),
                is_required=getattr(c, "is_required", True),
            )
            for c in criteria
        ],
        organization_name=org.name if org else "",
        evaluated_employee_name=target_emp.full_name if target_emp else "",
        criterion_set_name=crit_set.name,
        saved_answers=saved_answers,
    )


@router.post("/evaluations/{evaluation_id}/draft", response_model=DraftSavedOut)
async def save_evaluation_draft(
    evaluation_id: int,
    data: SubmitEvaluationRequest,
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    """Save partial answers without finalizing the evaluation."""
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        raise HTTPException(status_code=403, detail="Employees cannot fill evaluations")

    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.organization_id != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if getattr(evaluation, "status", "") == "completed":
        raise HTTPException(status_code=400, detail="Evaluation is already completed")
    if evaluation.filled_by_employee_id != emp.id:
        raise HTTPException(status_code=403, detail="Only the evaluator can edit this draft")

    crit_set = await criterion_set_service.get_by_id(evaluation.criterion_set_id or 0)
    criterion_ids = crit_set.criterion_ids if crit_set else []
    criteria = await criterion_service.get_by_ids(criterion_ids or [])
    crit_map = {c.id: c for c in criteria}

    allowed_ids = set(crit_map.keys())
    for answer in data.answers:
        if answer.criterion_id not in allowed_ids:
            raise HTTPException(status_code=400, detail=f"Criterion {answer.criterion_id} is not part of this evaluation's set")

    n = await _persist_web_evaluation_answers(
        evaluation_id, data.answers, crit_map, cv_repo
    )
    if data.comment is not None:
        await evaluation_service.update(
            evaluation_id, UpdateEvaluationDTO(comment=data.comment)
        )
    return DraftSavedOut(saved_count=n)


@router.post("/evaluations/{evaluation_id}/submit", response_model=SubmitEvaluationResponse)
async def submit_evaluation(
    evaluation_id: int,
    data: SubmitEvaluationRequest,
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types):
        raise HTTPException(status_code=403, detail="Employees cannot fill evaluations")

    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.organization_id != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")

    crit_set = await criterion_set_service.get_by_id(evaluation.criterion_set_id or 0)
    criterion_ids = crit_set.criterion_ids if crit_set else []
    criteria = await criterion_service.get_by_ids(criterion_ids or [])
    crit_map = {c.id: c for c in criteria}

    allowed_ids = set(crit_map.keys())
    for answer in data.answers:
        if answer.criterion_id not in allowed_ids:
            raise HTTPException(status_code=400, detail=f"Criterion {answer.criterion_id} is not part of this evaluation's set")

    await _persist_web_evaluation_answers(
        evaluation_id, data.answers, crit_map, cv_repo
    )

    passed = 0
    failed = 0
    score_points: list[float] = []  # 0.0 – 1.0 per answered criterion

    for answer in data.answers:
        crit = crit_map.get(answer.criterion_id)
        if not crit:
            continue
        value_type = getattr(crit, "value_type", "boolean")

        if value_type == "boolean":
            bool_val = (
                answer.value if isinstance(answer.value, bool)
                else str(answer.value).lower() in ("true", "1")
            )
            if bool_val:
                passed += 1
                score_points.append(1.0)
            else:
                failed += 1
                score_points.append(0.0)
        elif value_type == "number":
            try:
                num = float(answer.value) if not isinstance(answer.value, bool) else 0.0
            except (ValueError, TypeError):
                num = 0.0
            norm = max(0.0, min(1.0, (num - 1.0) / 4.0)) if num > 0 else 0.0
            passed += 1
            score_points.append(norm)
        else:
            text_val = str(answer.value).strip()
            score_points.append(1.0 if text_val else 0.0)
            passed += 1 if text_val else 0

    total = len(data.answers)
    score_pct = (sum(score_points) / len(score_points) * 100.0) if score_points else 0.0

    update_dto = UpdateEvaluationDTO(
        score_percentage=score_pct,
        total_criteria=total,
        passed_criteria=passed,
        failed_criteria=failed,
        comment=data.comment,
        status="completed",
    )
    await evaluation_service.update(evaluation_id, update_dto)

    return SubmitEvaluationResponse(
        evaluation_id=evaluation_id,
        score_percentage=score_pct,
        passed_criteria=passed,
        failed_criteria=failed,
        total_criteria=total,
    )


# ── Export ───────────────────────────────────────────────────────────────────

async def _build_export_data(
    evaluation_id: int,
    emp,
    evaluation_service: EvaluationService,
    employee_service: EmployeeService,
    criterion_service: CriterionService,
    criterion_set_service: CriterionSetService,
    eval_type_service: EvaluationTypeService,
    org_service: OrganizationService,
    cv_repo: CriterionValueRepositoryAsyncpg,
) -> dict:
    """Gather all data needed to generate an evaluation report."""
    evaluation = await evaluation_service.get_by_id(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.organization_id != emp.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    emp_types = await employee_service.get_employee_types()
    if _is_employee_role(emp, emp_types) and not _can_view_own_or_related_evaluation(
        emp, evaluation
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # Names
    evaluated_emp = await employee_service.get_by_id(evaluation.evaluated_employee_id or 0)
    filler_emp = await employee_service.get_by_id(evaluation.filled_by_employee_id or 0)
    org = await org_service.get_by_id(emp.organization_id)
    eval_type = await eval_type_service.get_by_id(evaluation.evaluation_type_id)
    crit_set = await criterion_set_service.get_by_id(evaluation.criterion_set_id or 0)

    # Criterion values (answers)
    cv_list = await cv_repo.get_by_evaluation_id(evaluation_id)
    criterion_ids = [cv.criterion_id for cv in cv_list]
    criteria_objs = await criterion_service.get_by_ids(criterion_ids)
    crit_map = {c.id: c for c in criteria_objs}

    criteria_data = []
    bool_count = 0
    for cv in cv_list:
        crit = crit_map.get(cv.criterion_id)
        if not crit:
            continue
        vtype = getattr(crit, "value_type", "boolean")
        if vtype == "boolean":
            bool_count += 1
        criteria_data.append({
            "name": crit.name,
            "value_type": vtype,
            "value": cv.value,
            "comment": cv.notes or "",
        })

    eval_date = evaluation.evaluation_date
    date_str = eval_date.strftime("%d.%m.%Y") if eval_date else "—"

    return {
        "evaluation_id": evaluation_id,
        "evaluation_type_name": eval_type.name if eval_type else "—",
        "organization_name": org.name if org else "—",
        "evaluated_employee_name": evaluated_emp.full_name if evaluated_emp else "—",
        "filled_by_employee_name": filler_emp.full_name if filler_emp else "—",
        "evaluation_date": date_str,
        "criteria": criteria_data,
        "total_criteria": len(criteria_data),
        "passed_criteria": getattr(evaluation, "passed_criteria", 0) or 0,
        "failed_criteria": getattr(evaluation, "failed_criteria", 0) or 0,
        "score_percentage": getattr(evaluation, "score_percentage", 0.0) or 0.0,
        "criterion_set_name": crit_set.name if crit_set else None,
        "boolean_criteria_count": bool_count,
    }


@router.get("/evaluations/{evaluation_id}/export/excel")
async def export_evaluation_excel(
    evaluation_id: int,
    emp=Depends(get_current_web_employee_download),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    eval_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    org_service: OrganizationService = Depends(get_organization_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
    excel_service: ExcelReportService = Depends(get_excel_report_service),
):
    """Download evaluation report as Excel (.xlsx)."""
    data = await _build_export_data(
        evaluation_id, emp,
        evaluation_service, employee_service, criterion_service,
        criterion_set_service, eval_type_service, org_service, cv_repo,
    )
    path = excel_service.generate_evaluation_report(**data)
    filename = f"evaluation_{evaluation_id}.xlsx"

    def _iter():
        with open(path, "rb") as f:
            yield from f
        try:
            path.unlink()
        except Exception:
            pass

    return StreamingResponse(
        _iter(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/evaluations/{evaluation_id}/export/pdf")
async def export_evaluation_pdf(
    evaluation_id: int,
    emp=Depends(get_current_web_employee_download),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    criterion_set_service: CriterionSetService = Depends(get_criterion_set_service),
    eval_type_service: EvaluationTypeService = Depends(get_evaluation_type_service),
    org_service: OrganizationService = Depends(get_organization_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
    pdf_service: PDFReportService = Depends(get_pdf_report_service),
):
    """Download evaluation report as PDF."""
    data = await _build_export_data(
        evaluation_id, emp,
        evaluation_service, employee_service, criterion_service,
        criterion_set_service, eval_type_service, org_service, cv_repo,
    )
    path = pdf_service.generate_evaluation_report(**data)
    filename = f"evaluation_{evaluation_id}.pdf"

    def _iter():
        with open(path, "rb") as f:
            yield from f
        try:
            path.unlink()
        except Exception:
            pass

    return StreamingResponse(
        _iter(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics", response_model=AnalyticsOut)
async def get_analytics(
    emp=Depends(get_current_web_employee_pin_fresh),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    employee_service: EmployeeService = Depends(get_employee_service),
    criterion_service: CriterionService = Depends(get_criterion_service),
    cv_repo: CriterionValueRepositoryAsyncpg = Depends(get_criterion_value_repository),
):
    org_id = emp.organization_id
    evaluations = await evaluation_service.get_by_organization_id(org_id)
    employees = await employee_service.get_by_organization_id(org_id)
    emp_types = await employee_service.get_employee_types()
    is_employee_view = _is_employee_role(emp, emp_types)

    if is_employee_view:
        evaluations = [
            ev for ev in evaluations if getattr(ev, "evaluated_employee_id", None) == emp.id
        ]

    total = len(evaluations)
    scores = [
        ev.score_percentage
        for ev in evaluations
        if getattr(ev, "score_percentage", None) is not None
    ]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # Per-employee average
    emp_scores: dict[int, list[float]] = {}
    for ev in evaluations:
        eid = getattr(ev, "evaluated_employee_id", None)
        sc = getattr(ev, "score_percentage", None)
        if eid and sc is not None:
            emp_scores.setdefault(eid, []).append(sc)

    emp_map = {e.id: e.full_name for e in employees}
    top_employees = sorted(
        [
            {"id": eid, "name": emp_map.get(eid, ""), "avg": sum(s) / len(s), "count": len(s)}
            for eid, s in emp_scores.items()
        ],
        key=lambda x: x["avg"],
        reverse=True,
    )[:10]

    # Criteria stats (pass/fail aggregated per criterion)
    def _is_passed(val):
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
        values = await cv_repo.get_by_evaluation_id(ev.id)
        for cv in values:
            if cv.criterion_id not in criteria_agg:
                criteria_agg[cv.criterion_id] = {"passed": 0, "failed": 0}
            passed = _is_passed(cv.value)
            if passed is None:
                continue
            if passed:
                criteria_agg[cv.criterion_id]["passed"] += 1
            else:
                criteria_agg[cv.criterion_id]["failed"] += 1

    criteria_stats = []
    if criteria_agg:
        all_criteria = await criterion_service.get_by_organization_id(org_id)
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

    monthly_scores: list[float] = []
    my_evaluations: list[dict] = []
    if is_employee_view:
        now = datetime.utcnow()
        month_start = datetime(now.year, now.month, 1)
        for ev in sorted(
            evaluations,
            key=lambda x: str(getattr(x, "created_at", "")),
            reverse=True,
        ):
            score = getattr(ev, "score_percentage", None)
            created_at = getattr(ev, "created_at", None)
            if score is not None and created_at:
                created_dt = created_at.replace(tzinfo=None) if getattr(created_at, "tzinfo", None) else created_at
                if created_dt >= month_start:
                    monthly_scores.append(float(score))
            my_evaluations.append(
                {
                    "id": ev.id,
                    "filled_by_employee_id": getattr(ev, "filled_by_employee_id", None),
                    "filled_by_employee_name": emp_map.get(getattr(ev, "filled_by_employee_id", 0), "—"),
                    "created_at": str(getattr(ev, "created_at", "")),
                    "score_percentage": float(score) if score is not None else None,
                    "status": getattr(ev, "status", ""),
                }
            )

    return AnalyticsOut(
        total_evaluations=total,
        average_score=round(avg_score, 1),
        employees_count=(1 if is_employee_view else len(employees)),
        top_employees=top_employees,
        criteria_stats=criteria_stats,
        is_personal_view=is_employee_view,
        monthly_average_score=round(sum(monthly_scores) / len(monthly_scores), 1) if monthly_scores else 0.0,
        my_evaluations=my_evaluations[:30],
    )
