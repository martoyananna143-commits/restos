"""DTOs for Evaluation repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EvaluationDTO:
    """Data Transfer Object for Evaluation."""

    id: int
    evaluation_type_id: int
    organization_id: int
    filled_by_employee_id: int
    evaluated_employee_id: Optional[int]
    criterion_set_id: Optional[int]
    evaluation_date: datetime
    total_criteria: int
    passed_criteria: int
    failed_criteria: int
    score_percentage: float
    comment: Optional[str]
    status: str
    meta: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


@dataclass
class CreateEvaluationDTO:
    """Data Transfer Object for creating Evaluation."""

    evaluation_type_id: int
    organization_id: int
    filled_by_employee_id: int
    evaluated_employee_id: Optional[int] = None
    criterion_set_id: Optional[int] = None
    evaluation_date: Optional[datetime] = None
    total_criteria: int = 0
    passed_criteria: int = 0
    failed_criteria: int = 0
    score_percentage: float = 0.0
    comment: Optional[str] = None
    status: str = "draft"
    meta: Optional[dict] = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


@dataclass
class UpdateEvaluationDTO:
    """Data Transfer Object for updating Evaluation."""

    evaluation_type_id: Optional[int] = None
    organization_id: Optional[int] = None
    filled_by_employee_id: Optional[int] = None
    evaluated_employee_id: Optional[int] = None
    criterion_set_id: Optional[int] = None
    evaluation_date: Optional[datetime] = None
    total_criteria: Optional[int] = None
    passed_criteria: Optional[int] = None
    failed_criteria: Optional[int] = None
    score_percentage: Optional[float] = None
    comment: Optional[str] = None
    status: Optional[str] = None
    meta: Optional[dict] = None

