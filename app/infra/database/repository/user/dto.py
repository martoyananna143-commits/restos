"""DTOs for User repository."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class UserDTO:
    """Data Transfer Object for User."""

    id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    chat_id: int
    is_verified: bool
    is_active: bool
    joined_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    version: Optional[int] = None


@dataclass
class CreateUserDTO:
    """Data Transfer Object for creating User."""

    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    chat_id: int
    is_verified: bool = False
    is_active: bool = True
    joined_at: datetime = None


@dataclass
class UpdateUserDTO:
    """Data Transfer Object for updating User."""

    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_verified: Optional[bool] = None
    is_active: Optional[bool] = None
    version: Optional[int] = None


@dataclass
class TelegramUserDTO:
    """Data Transfer Object for Telegram user data."""

    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    version: int

