"""Users API router."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_user_service
from app.api.schemas import (
    UserCreate,
    UserResponse,
)
from app.infra.database.repository.user.dto import TelegramUserDTO
from app.internal.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{telegram_id}", response_model=UserResponse)
async def get_user(
    telegram_id: int,
    chat_id: int,
    service: UserService = Depends(get_user_service),
):
    """Get user by Telegram ID and chat ID.
    
    Args:
        telegram_id: Telegram user ID.
        chat_id: Chat ID.
        service: User service dependency.
        
    Returns:
        User details.
        
    Raises:
        HTTPException: If user not found.
    """
    # This requires a get method in the repository
    # For now, we'll use get_or_create_user which may create if not exists
    telegram_user = TelegramUserDTO(
        telegram_id=telegram_id,
        username=None,
        first_name=None,
        last_name=None,
    )
    
    user, _ = await service.get_or_create_user(telegram_user, chat_id)
    return user


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_or_sync_user(
    data: UserCreate,
    service: UserService = Depends(get_user_service),
):
    """Create or synchronize user.
    
    Args:
        data: User creation/sync data.
        service: User service dependency.
        
    Returns:
        User details.
    """
    telegram_user = TelegramUserDTO(
        telegram_id=data.telegram_id,
        username=data.username,
        first_name=data.first_name,
        last_name=data.last_name,
    )
    
    user, created = await service.get_or_create_user(telegram_user, data.chat_id)
    
    if not created:
        # Sync user data
        synced_user = await service.sync_user_with_telegram(telegram_user, data.chat_id)
        if synced_user:
            user = synced_user
    
    return user
