"""Evaluation service for business logic."""

from typing import Optional, List

from app.infra.database.repository.evaluation.dto import (
    CreateEvaluationDTO,
    EvaluationDTO,
    UpdateEvaluationDTO,
)
from app.infra.database.repository.evaluation.evaluation_asyncpg import (
    EvaluationRepositoryAsyncpg,
)


class EvaluationService:
    """Service for evaluation operations."""

    def __init__(self, repository: EvaluationRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: Evaluation repository instance.
        """
        self.repository = repository

    async def get_by_id(self, evaluation_id: int) -> Optional[EvaluationDTO]:
        """Get evaluation by ID.

        Args:
            evaluation_id: Evaluation ID.

        Returns:
            EvaluationDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(evaluation_id)

    async def create(self, dto: CreateEvaluationDTO) -> EvaluationDTO:
        """Create a new evaluation.

        Args:
            dto: CreateEvaluationDTO with evaluation data.

        Returns:
            Created EvaluationDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, evaluation_id: int, dto: UpdateEvaluationDTO
    ) -> Optional[EvaluationDTO]:
        """Update evaluation data.

        Args:
            evaluation_id: Evaluation ID to update.
            dto: UpdateEvaluationDTO with fields to update.

        Returns:
            Updated EvaluationDTO instance or None if not found.
        """
        return await self.repository.update(evaluation_id, dto)

    async def calculate_scores(self, evaluation_id: int) -> Optional[EvaluationDTO]:
        """Calculate and update scores for an evaluation.

        Args:
            evaluation_id: Evaluation ID.

        Returns:
            Updated EvaluationDTO instance or None if not found.
        """
        # This will be implemented when we have CriterionValue repository
        # For now, just return the evaluation
        return await self.repository.get_by_id(evaluation_id)

    async def get_all(self) -> List[EvaluationDTO]:
        """Get all evaluations across all organizations.

        Returns:
            List of EvaluationDTO instances.
        """
        return await self.repository.get_all()

    async def get_by_organization_id(self, organization_id: int) -> List[EvaluationDTO]:
        """Get all evaluations by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            List of EvaluationDTO instances.
        """
        return await self.repository.get_by_organization_id(organization_id)

    async def get_by_employee_id(self, employee_id: int) -> List[EvaluationDTO]:
        """Get evaluations where employee participated (as filler or evaluated).

        Args:
            employee_id: Employee ID.

        Returns:
            List of EvaluationDTO instances.
        """
        return await self.repository.get_by_employee_id(employee_id)

    async def delete(self, evaluation_id: int) -> bool:
        """Delete evaluation (soft delete).

        Args:
            evaluation_id: Evaluation ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        return await self.repository.delete(evaluation_id)
















