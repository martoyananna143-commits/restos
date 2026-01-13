"""CriterionSet service for business logic."""

from typing import Optional

from app.infra.database.repository.criterion_set.dto import (
    CreateCriterionSetDTO,
    CriterionSetDTO,
    UpdateCriterionSetDTO,
)
from app.infra.database.repository.criterion_set.criterion_set_asyncpg import (
    CriterionSetRepositoryAsyncpg,
)


class CriterionSetService:
    """Service for criterion set operations."""

    def __init__(self, repository: CriterionSetRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: CriterionSet repository instance.
        """
        self.repository = repository

    async def get_by_id(self, criterion_set_id: int) -> Optional[CriterionSetDTO]:
        """Get criterion set by ID.

        Args:
            criterion_set_id: CriterionSet ID.

        Returns:
            CriterionSetDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(criterion_set_id)

    async def get_by_organization_id(
        self, organization_id: int, include_inactive: bool = False
    ) -> list[CriterionSetDTO]:
        """Get all criterion sets by organization ID.

        Args:
            organization_id: Organization ID.
            include_inactive: Include inactive sets.

        Returns:
            List of CriterionSetDTO instances.
        """
        return await self.repository.get_by_organization_id(organization_id, include_inactive)

    async def get_default_by_organization_id(
        self, organization_id: int
    ) -> Optional[CriterionSetDTO]:
        """Get default criterion set by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            CriterionSetDTO if found, None otherwise.
        """
        return await self.repository.get_default_by_organization_id(organization_id)

    async def create(self, dto: CreateCriterionSetDTO) -> CriterionSetDTO:
        """Create a new criterion set.

        Args:
            dto: CreateCriterionSetDTO with criterion set data.

        Returns:
            Created CriterionSetDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, criterion_set_id: int, dto: UpdateCriterionSetDTO
    ) -> Optional[CriterionSetDTO]:
        """Update criterion set data.

        Args:
            criterion_set_id: CriterionSet ID to update.
            dto: UpdateCriterionSetDTO with fields to update.

        Returns:
            Updated CriterionSetDTO instance or None if not found.
        """
        return await self.repository.update(criterion_set_id, dto)

    async def delete(self, criterion_set_id: int) -> bool:
        """Soft delete criterion set.

        Args:
            criterion_set_id: CriterionSet ID.

        Returns:
            True if deleted, False otherwise.
        """
        return await self.repository.delete(criterion_set_id)

