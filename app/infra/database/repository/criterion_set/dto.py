"""DTOs for CriterionSet repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class CriterionSetDTO:
    """Data Transfer Object for CriterionSet."""

    id: int
    organization_id: int
    name: str
    description: Optional[str]
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    criterion_ids: Optional[list[int]] = None  # IDs критериев в наборе
    source_type: str = "internal"
    source_url: Optional[str] = None
    source_meta: Optional[dict[str, Any]] = None


@dataclass
class CreateCriterionSetDTO:
    """Data Transfer Object for creating CriterionSet."""

    organization_id: int
    name: str
    description: Optional[str] = None
    is_default: bool = False
    is_active: bool = True
    criterion_ids: Optional[list[int]] = None  # IDs критериев для добавления в набор
    source_type: str = "internal"
    source_url: Optional[str] = None
    source_meta: Optional[dict[str, Any]] = None


@dataclass
class UpdateCriterionSetDTO:
    """Data Transfer Object for updating CriterionSet."""

    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    criterion_ids: Optional[list[int]] = None  # IDs критериев для обновления набора
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    source_meta: Optional[dict[str, Any]] = None

