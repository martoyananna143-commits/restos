"""DTOs for EvaluationType repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EvaluationTypeDTO:
    """Data Transfer Object for EvaluationType."""

    id: int
    organization_id: Optional[int]
    name: str
    code: str
    description: Optional[str]
    is_active: bool
    config: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


@dataclass
class CreateEvaluationTypeDTO:
    """Data Transfer Object for creating EvaluationType."""

    organization_id: int
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool = True
    config: dict = None

    def __post_init__(self):
        if self.config is None:
            self.config = {}


@dataclass
class UpdateEvaluationTypeDTO:
    """Data Transfer Object for updating EvaluationType."""

    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None

