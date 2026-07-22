"""Pydantic schemas for web data API."""

from typing import Any, Optional

from pydantic import BaseModel

# ── Response schemas ─────────────────────────────────────────────────────────

class EmployeeOut(BaseModel):
    id: int
    full_name: str
    position: Optional[str] = None
    employee_type_id: int
    is_admin: bool = False
    is_active: bool = True


class EmployeeTypeOut(BaseModel):
    id: int
    name: str
    code: str
    is_administrator: bool = False


class EvaluationTypeOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None


class CriterionSetOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_default: bool = False
    criterion_ids: Optional[list[int]] = None
    source_type: str = "internal"
    source_url: Optional[str] = None
    source_meta: Optional[dict[str, Any]] = None




class GoogleSheetPreviewIn(BaseModel):
    url: str


class GoogleSheetPreviewRowOut(BaseModel):
    block: str
    criterion: str
    value_type: str


class GoogleSheetPreviewOut(BaseModel):
    rows_count: int
    blocks: list[str]
    sample_rows: list[GoogleSheetPreviewRowOut]
    spreadsheet_id: str


class GoogleSheetCreateIn(BaseModel):
    name: str
    url: str


class GoogleDriveBrowseIn(BaseModel):
    folder_url: str


class GoogleDriveFileOut(BaseModel):
    file_id: str
    name: str
    modified_time: Optional[str] = None
    web_view_link: Optional[str] = None


class GoogleDriveBrowseOut(BaseModel):
    files: list[GoogleDriveFileOut]


class GoogleSheetFromFolderIn(BaseModel):
    folder_url: str
    file_id: str
    name: str


class CriterionSetCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False
    criterion_ids: list[int] = []


class CriterionSetUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    criterion_ids: Optional[list[int]] = None


class CriterionCreateIn(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    value_type: str = "boolean"  # boolean, string, number
    is_required: bool = True


class CriterionUpdateIn(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    value_type: Optional[str] = None
    is_required: Optional[bool] = None


class CriterionOut(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str] = None
    value_type: str = "boolean"
    is_required: bool = True


class AnalyticsOut(BaseModel):
    total_evaluations: int
    average_score: float
    employees_count: int
    top_employees: list[dict]
    criteria_stats: list[dict]
    is_personal_view: bool = False
    monthly_average_score: float = 0.0
    my_evaluations: list[dict] = []


class EvaluationOut(BaseModel):
    id: int
    evaluated_employee_id: Optional[int] = None
    evaluated_employee_name: Optional[str] = None
    evaluation_type_id: int
    evaluation_type_name: Optional[str] = None
    criterion_set_id: int
    score_percentage: Optional[float] = None
    status: str = "completed"
    created_at: str


class FormDataOut(BaseModel):
    criteria: list[CriterionOut]
    organization_name: str
    evaluated_employee_name: Optional[str] = None
    criterion_set_name: Optional[str] = None
    evaluation_id: int


class AnswerIn(BaseModel):
    criterion_id: int
    value: bool | str | float | int
    comment: Optional[str] = None


class StartEvaluationRequest(BaseModel):
    evaluated_employee_id: int
    criterion_set_id: int
    evaluation_type_id: int


class StartEvaluationResponse(BaseModel):
    evaluation_id: int
    criteria: list[CriterionOut]
    organization_name: str
    evaluated_employee_name: str
    criterion_set_name: str


class ResumeEvaluationResponse(BaseModel):
    """Same as starting an evaluation, plus saved answers for the form."""

    evaluation_id: int
    criteria: list[CriterionOut]
    organization_name: str
    evaluated_employee_name: str
    criterion_set_name: str
    saved_answers: list[AnswerIn]


class DraftSavedOut(BaseModel):
    ok: bool = True
    saved_count: int


class SubmitEvaluationRequest(BaseModel):
    answers: list[AnswerIn]
    comment: Optional[str] = None


class SubmitEvaluationResponse(BaseModel):
    evaluation_id: int
    score_percentage: float
    passed_criteria: int
    failed_criteria: int
    total_criteria: int


class EvaluationCriterionAnswerOut(BaseModel):
    name: str
    value_type: str = "boolean"
    value: Any = None
    comment: str = ""


class EvaluationDetailOut(BaseModel):
    evaluation_id: int
    organization_name: str
    evaluation_type_name: str
    criterion_set_name: Optional[str] = None
    evaluated_employee_name: str
    filled_by_employee_name: str
    evaluation_date: str
    score_percentage: Optional[float] = None
    passed_criteria: int
    failed_criteria: int
    total_criteria: int
    status: str
    comment: Optional[str] = None
    criteria: list[EvaluationCriterionAnswerOut]


class UpdateRoleRequest(BaseModel):
    employee_type_id: int


class InvitationCreateIn(BaseModel):
    employee_type_id: int
    position: Optional[str] = None
    full_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_telegram: Optional[str] = None
    ttl_seconds: int = 86400 * 7


class InvitationOut(BaseModel):
    code: str
    invite_url: str
    organization_id: int
    employee_type_id: Optional[int] = None
    employee_type_name: Optional[str] = None
    position: Optional[str] = None
    full_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_telegram: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    used: bool = False


class AIMessageIn(BaseModel):
    role: str
    content: str


class AIMessageOut(BaseModel):
    role: str
    content: str


class AIChatIn(BaseModel):
    message: str
    conversation_history: list[AIMessageIn] = []
    mode: str = "general"


class AIChatOut(BaseModel):
    response: str
    conversation_history: list[AIMessageOut]


class AICreateCriterionSetIn(BaseModel):
    prompt: str
    set_name: Optional[str] = None
    description: Optional[str] = None
    is_default: bool = False


class AICreateCriterionSetOut(BaseModel):
    set_id: int
    set_name: str
    criteria_created: int
    criterion_ids: list[int]
    ai_response: str


# ── Two-step AI flow (preview → confirm) ─────────────────────────────────────

class AICriterionPreviewItem(BaseModel):
    name: str
    value_type: str = "boolean"
    description: Optional[str] = None
    is_required: bool = True


class AIPreviewCriterionSetIn(BaseModel):
    """Step 1: generate without saving."""
    prompt: str
    set_name: Optional[str] = None
    description: Optional[str] = None


class AIPreviewCriterionSetOut(BaseModel):
    set_name: str
    description: Optional[str] = None
    criteria: list[AICriterionPreviewItem]
    ai_response: str


class AIConfirmCriterionSetIn(BaseModel):
    """Step 2: save user-edited preview."""
    set_name: str
    description: Optional[str] = None
    is_default: bool = False
    criteria: list[AICriterionPreviewItem]

class EvaluationTypeCreateIn(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class EvaluationTypeUpdateIn(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
