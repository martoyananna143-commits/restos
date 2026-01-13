"""EvaluationType service for business logic."""

from typing import Optional

from app.infra.database.repository.evaluation_type.dto import (
    CreateEvaluationTypeDTO,
    EvaluationTypeDTO,
    UpdateEvaluationTypeDTO,
)
from app.infra.database.repository.evaluation_type.evaluation_type_asyncpg import (
    EvaluationTypeRepositoryAsyncpg,
)


class EvaluationTypeService:
    """Service for evaluation type operations."""

    def __init__(self, repository: EvaluationTypeRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: EvaluationType repository instance.
        """
        self.repository = repository

    async def get_all(self) -> list[EvaluationTypeDTO]:
        """Get all active evaluation types.

        Returns:
            List of EvaluationTypeDTO instances.
        """
        return await self.repository.get_all()

    async def get_by_id(self, evaluation_type_id: int) -> Optional[EvaluationTypeDTO]:
        """Get evaluation type by ID.

        Args:
            evaluation_type_id: Evaluation type ID.

        Returns:
            EvaluationTypeDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(evaluation_type_id)

    async def create(
        self, dto: CreateEvaluationTypeDTO
    ) -> EvaluationTypeDTO:
        """Create a new evaluation type.

        Args:
            dto: CreateEvaluationTypeDTO with evaluation type data.

        Returns:
            Created EvaluationTypeDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, evaluation_type_id: int, dto: UpdateEvaluationTypeDTO
    ) -> Optional[EvaluationTypeDTO]:
        """Update evaluation type data.

        Args:
            evaluation_type_id: Evaluation type ID to update.
            dto: UpdateEvaluationTypeDTO with fields to update.

        Returns:
            Updated EvaluationTypeDTO instance or None if not found.
        """
        # TODO: Implement update method in repository if needed
        return None

