"""DTOs for CriterionValue repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union


@dataclass
class CriterionValueDTO:
    """Data Transfer Object for CriterionValue."""

    id: int
    evaluation_id: int
    criterion_id: int
    value: Union[bool, str, float, int]  # Может быть bool, str, или число
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class CreateCriterionValueDTO:
    """Data Transfer Object for creating CriterionValue."""

    evaluation_id: int
    criterion_id: int
    value: Union[bool, str, float, int]  # Может быть bool, str, или число
    notes: Optional[str] = None


@dataclass
class UpdateCriterionValueDTO:
    """Data Transfer Object for updating CriterionValue."""

    value: Optional[Union[bool, str, float, int]] = None
    notes: Optional[str] = None





