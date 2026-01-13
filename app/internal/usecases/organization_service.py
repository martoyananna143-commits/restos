"""Organization service for business logic."""

from typing import Optional

from app.infra.database.repository.organization.dto import (
    CreateOrganizationDTO,
    OrganizationDTO,
    UpdateOrganizationDTO,
)
from app.infra.database.repository.organization.organization_asyncpg import (
    OrganizationRepositoryAsyncpg,
)


class OrganizationService:
    """Service for organization operations."""

    def __init__(self, repository: OrganizationRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: Organization repository instance.
        """
        self.repository = repository

    async def get_by_user_telegram_id(
        self, telegram_id: int
    ) -> Optional[OrganizationDTO]:
        """Get first organization by user telegram ID.

        Args:
            telegram_id: User telegram ID.

        Returns:
            OrganizationDTO if found, None otherwise.
        """
        return await self.repository.get_by_user_telegram_id(telegram_id)

    async def get_all_by_user_telegram_id(
        self, telegram_id: int
    ) -> list[OrganizationDTO]:
        """Get all organizations by user telegram ID.

        Args:
            telegram_id: User telegram ID.

        Returns:
            List of OrganizationDTO instances.
        """
        return await self.repository.get_all_by_user_telegram_id(telegram_id)

    async def get_by_id(self, organization_id: int) -> Optional[OrganizationDTO]:
        """Get organization by ID.

        Args:
            organization_id: Organization ID.

        Returns:
            OrganizationDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(organization_id)

    async def create(
        self, dto: CreateOrganizationDTO
    ) -> OrganizationDTO:
        """Create a new organization.

        Args:
            dto: CreateOrganizationDTO with organization data.

        Returns:
            Created OrganizationDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, organization_id: int, dto: UpdateOrganizationDTO
    ) -> Optional[OrganizationDTO]:
        """Update organization data.

        Args:
            organization_id: Organization ID to update.
            dto: UpdateOrganizationDTO with fields to update.

        Returns:
            Updated OrganizationDTO instance or None if not found.
        """
        return await self.repository.update(organization_id, dto)

