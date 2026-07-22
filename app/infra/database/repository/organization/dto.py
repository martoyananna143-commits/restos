"""DTOs for Organization repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OrganizationDTO:
    """Data Transfer Object for Organization."""

    id: int
    name: str
    code: str
    address: Optional[str]
    phone: Optional[str]
    is_active: bool
    meta: dict
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


@dataclass
class CreateOrganizationDTO:
    """Data Transfer Object for creating Organization."""

    name: str
    code: str
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    meta: dict = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


@dataclass
class UpdateOrganizationDTO:
    """Data Transfer Object for updating Organization."""

    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    meta: Optional[dict] = None

