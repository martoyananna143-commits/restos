"""DTOs for Criterion repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CriterionDTO:
    """Data Transfer Object for Criterion."""

    id: int
    organization_id: int
    category_id: Optional[int]
    name: str
    code: str
    description: Optional[str]
    sort_order: int
    is_required: bool
    is_active: bool
    value_type: str  # 'boolean', 'string', 'number'
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


@dataclass
class CreateCriterionDTO:
    """Data Transfer Object for creating Criterion."""

    organization_id: int
    name: str
    code: str
    category_id: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0
    is_required: bool = True
    is_active: bool = True
    value_type: str = "boolean"  # 'boolean', 'string', 'number'


@dataclass
class UpdateCriterionDTO:
    """Data Transfer Object for updating Criterion."""

    organization_id: Optional[int] = None
    category_id: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None
    value_type: Optional[str] = None  # 'boolean', 'string', 'number'

