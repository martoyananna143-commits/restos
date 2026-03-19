"""Invitation service for managing employee invitation codes."""

import json
import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)


class InvitationService:
    """Service for managing employee invitation codes."""

    def __init__(self, storage):
        """Initialize invitation service.

        Args:
            storage: Redis storage instance for persisting invitation codes.
        """
        self.storage = storage

    def _get_redis_key(self, code: str) -> str:
        """Get Redis key for invitation code.

        Args:
            code: Invitation code.

        Returns:
            Redis key string.
        """
        return f"invitation:{code}"

    def _generate_code(self) -> str:
        """Generate a unique invitation code.

        Returns:
            Unique invitation code string.
        """
        # Generate a secure random code (32 characters)
        return secrets.token_urlsafe(24)

    async def create_invitation(
        self,
        inviter_telegram_id: int,
        organization_id: Optional[int] = None,
        invitation_type: str = "employee",
        employee_type_id: Optional[int] = None,
        ttl: int = 86400 * 7,
    ) -> str:
        """Create a new invitation code.

        Args:
            inviter_telegram_id: Telegram ID of the user who creates the invitation.
            organization_id: Organization ID to invite to (None for admin invitations).
            invitation_type: Type of invitation - "employee" or "admin" (default: "employee").
            employee_type_id: Role to assign on acceptance (1=employee, 2=manager, 3=admin).
            ttl: Time to live in seconds (default: 7 days).

        Returns:
            Invitation code string.
        """
        code = self._generate_code()
        redis_key = self._get_redis_key(code)

        invitation_data = {
            "inviter_telegram_id": inviter_telegram_id,
            "organization_id": organization_id,
            "invitation_type": invitation_type,
            "employee_type_id": employee_type_id,
            "used": False,
        }

        try:
            if hasattr(self.storage, '_redis') and self.storage._redis:
                redis_client = self.storage._redis
                await redis_client.set(
                    redis_key,
                    json.dumps(invitation_data, ensure_ascii=False),
                    ex=ttl,
                )
            elif hasattr(self.storage, 'redis'):
                await self.storage.redis.set(
                    redis_key,
                    json.dumps(invitation_data, ensure_ascii=False),
                    ex=ttl,
                )
            else:
                logger.warning(
                    f"Storage does not have direct Redis access. Storage type: {type(self.storage)}"
                )
                # Fallback to memory storage (not recommended for production)
                if hasattr(self.storage, 'data'):
                    self.storage.data[redis_key] = invitation_data

            if invitation_type == "admin":
                logger.info(
                    f"Created admin invitation code {code} "
                    f"by user {inviter_telegram_id}"
                )
            else:
                logger.info(
                    f"Created invitation code {code} for organization {organization_id} "
                    f"by user {inviter_telegram_id}"
                )
            return code
        except Exception as e:
            logger.error(f"Error creating invitation code: {e}", exc_info=True)
            raise

    async def get_invitation(self, code: str) -> Optional[dict]:
        """Get invitation data by code.

        Args:
            code: Invitation code.

        Returns:
            Dictionary with invitation data or None if not found/used.
        """
        redis_key = self._get_redis_key(code)

        try:
            if hasattr(self.storage, '_redis') and self.storage._redis:
                redis_client = self.storage._redis
                data_str = await redis_client.get(redis_key)
                if data_str:
                    if isinstance(data_str, bytes):
                        data_str = data_str.decode('utf-8')
                    return json.loads(data_str)
            elif hasattr(self.storage, 'redis'):
                data_str = await self.storage.redis.get(redis_key)
                if data_str:
                    if isinstance(data_str, bytes):
                        data_str = data_str.decode('utf-8')
                    return json.loads(data_str)
            else:
                # Fallback to memory storage
                if hasattr(self.storage, 'data'):
                    return self.storage.data.get(redis_key)

            return None
        except Exception as e:
            logger.error(f"Error getting invitation code: {e}", exc_info=True)
            return None

    async def use_invitation(self, code: str) -> Optional[dict]:
        """Mark invitation as used and return its data.

        Args:
            code: Invitation code.

        Returns:
            Dictionary with invitation data or None if not found/already used.
        """
        invitation_data = await self.get_invitation(code)

        if not invitation_data:
            return None

        if invitation_data.get("used", False):
            logger.warning(f"Attempt to use already used invitation code: {code}")
            return None

        # Mark as used
        invitation_data["used"] = True
        redis_key = self._get_redis_key(code)

        try:
            # Update in Redis with shorter TTL (keep for 1 day after use for audit)
            if hasattr(self.storage, '_redis') and self.storage._redis:
                redis_client = self.storage._redis
                await redis_client.set(
                    redis_key,
                    json.dumps(invitation_data, ensure_ascii=False),
                    ex=86400,  # 1 day
                )
            elif hasattr(self.storage, 'redis'):
                await self.storage.redis.set(
                    redis_key,
                    json.dumps(invitation_data, ensure_ascii=False),
                    ex=86400,  # 1 day
                )
            else:
                # Fallback to memory storage
                if hasattr(self.storage, 'data'):
                    self.storage.data[redis_key] = invitation_data

            logger.info(f"Invitation code {code} marked as used")
            return invitation_data
        except Exception as e:
            logger.error(f"Error using invitation code: {e}", exc_info=True)
            return None

    async def delete_invitation(self, code: str) -> bool:
        """Delete invitation code.

        Args:
            code: Invitation code.

        Returns:
            True if deleted, False otherwise.
        """
        redis_key = self._get_redis_key(code)

        try:
            if hasattr(self.storage, '_redis') and self.storage._redis:
                redis_client = self.storage._redis
                result = await redis_client.delete(redis_key)
                return result > 0
            elif hasattr(self.storage, 'redis'):
                result = await self.storage.redis.delete(redis_key)
                return result > 0
            else:
                # Fallback to memory storage
                if hasattr(self.storage, 'data'):
                    if redis_key in self.storage.data:
                        del self.storage.data[redis_key]
                        return True
                return False
        except Exception as e:
            logger.error(f"Error deleting invitation code: {e}", exc_info=True)
            return False



