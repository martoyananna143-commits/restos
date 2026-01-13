"""Criterion service for business logic."""

from typing import Optional

from app.infra.database.repository.criterion.dto import (
    CreateCriterionDTO,
    CriterionDTO,
    UpdateCriterionDTO,
)
from app.infra.database.repository.criterion.criterion_asyncpg import (
    CriterionRepositoryAsyncpg,
)


class CriterionService:
    """Service for criterion operations."""

    def __init__(self, repository: CriterionRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: Criterion repository instance.
        """
        self.repository = repository

    async def get_by_id(self, criterion_id: int) -> Optional[CriterionDTO]:
        """Get criterion by ID.

        Args:
            criterion_id: Criterion ID.

        Returns:
            CriterionDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(criterion_id)

    async def get_by_organization_id(
        self, organization_id: int
    ) -> list[CriterionDTO]:
        """Get all criteria by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            List of CriterionDTO instances.
        """
        return await self.repository.get_by_organization_id(organization_id)

    async def get_by_evaluation_type_id(
        self, evaluation_type_id: int
    ) -> list[CriterionDTO]:
        """Get all criteria by evaluation type ID.

        Args:
            evaluation_type_id: Evaluation type ID.

        Returns:
            List of CriterionDTO instances.
        """
        return await self.repository.get_by_evaluation_type_id(evaluation_type_id)

    async def get_by_ids(self, criterion_ids: list[int]) -> list[CriterionDTO]:
        """Get criteria by list of IDs.

        Args:
            criterion_ids: List of criterion IDs.

        Returns:
            List of CriterionDTO instances.
        """
        return await self.repository.get_by_ids(criterion_ids)

    async def create(self, dto: CreateCriterionDTO) -> CriterionDTO:
        """Create a new criterion.

        Args:
            dto: CreateCriterionDTO with criterion data.

        Returns:
            Created CriterionDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, criterion_id: int, dto: UpdateCriterionDTO
    ) -> Optional[CriterionDTO]:
        """Update criterion data.

        Args:
            criterion_id: Criterion ID to update.
            dto: UpdateCriterionDTO with fields to update.

        Returns:
            Updated CriterionDTO instance or None if not found.
        """
        return await self.repository.update(criterion_id, dto)

