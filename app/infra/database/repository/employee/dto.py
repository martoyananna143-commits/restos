"""DTOs for Employee repository."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class EmployeeDTO:
    """Data Transfer Object for Employee."""

    id: int
    telegram_id: Optional[int]
    employee_type_id: int
    organization_id: int
    full_name: str
    username: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    hire_date: Optional[date]
    is_active: bool
    meta: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


@dataclass
class CreateEmployeeDTO:
    """Data Transfer Object for creating Employee."""

    employee_type_id: int
    organization_id: int
    full_name: str
    username: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    hire_date: Optional[date] = None
    telegram_id: Optional[int] = None
    is_active: bool = True
    meta: dict = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


@dataclass
class UpdateEmployeeDTO:
    """Data Transfer Object for updating Employee."""

    employee_type_id: Optional[int] = None
    organization_id: Optional[int] = None
    full_name: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    hire_date: Optional[date] = None
    telegram_id: Optional[int] = None
    is_active: Optional[bool] = None
    meta: Optional[dict] = None

