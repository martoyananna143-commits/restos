"""Evaluation service for business logic."""

from typing import Optional

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
















