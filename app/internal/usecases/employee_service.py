"""Employee service for business logic."""

from typing import Optional

from app.infra.database.repository.employee.dto import (
    CreateEmployeeDTO,
    EmployeeDTO,
    UpdateEmployeeDTO,
)
from app.infra.database.repository.employee.employee_asyncpg import (
    EmployeeRepositoryAsyncpg,
)


class EmployeeService:
    """Service for employee operations."""

    def __init__(self, repository: EmployeeRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: Employee repository instance.
        """
        self.repository = repository

    async def get_by_organization_id(
        self, organization_id: int
    ) -> list[EmployeeDTO]:
        """Get all employees by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            List of EmployeeDTO instances.
        """
        return await self.repository.get_by_organization_id(organization_id)

    async def get_by_id(self, employee_id: int) -> Optional[EmployeeDTO]:
        """Get employee by ID.

        Args:
            employee_id: Employee ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        return await self.repository.get_by_id(employee_id)

    async def create(self, dto: CreateEmployeeDTO) -> EmployeeDTO:
        """Create a new employee.

        Args:
            dto: CreateEmployeeDTO with employee data.

        Returns:
            Created EmployeeDTO instance.
        """
        return await self.repository.create(dto)

    async def update(
        self, employee_id: int, dto: UpdateEmployeeDTO
    ) -> Optional[EmployeeDTO]:
        """Update employee data.

        Args:
            employee_id: Employee ID to update.
            dto: UpdateEmployeeDTO with fields to update.

        Returns:
            Updated EmployeeDTO instance or None if not found.
        """
        return await self.repository.update(employee_id, dto)

    async def delete(self, employee_id: int) -> bool:
        """Soft delete employee.

        Args:
            employee_id: Employee ID.

        Returns:
            True if deleted, False otherwise.
        """
        return await self.repository.delete(employee_id)

    async def restore(self, employee_id: int) -> bool:
        """Restore soft-deleted employee.

        Args:
            employee_id: Employee ID.

        Returns:
            True if restored, False otherwise.
        """
        return await self.repository.restore(employee_id)

    async def get_by_organization_id_with_deleted(
        self, organization_id: int
    ) -> list[EmployeeDTO]:
        """Get all employees by organization ID including deleted ones.

        Args:
            organization_id: Organization ID.

        Returns:
            List of EmployeeDTO instances (including deleted).
        """
        return await self.repository.get_by_organization_id_with_deleted(
            organization_id
        )

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[EmployeeDTO]:
        """Get employee by telegram_id.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        return await self.repository.get_by_telegram_id(telegram_id)

    async def get_by_telegram_id_and_organization_id(
        self, telegram_id: int, organization_id: int
    ) -> Optional[EmployeeDTO]:
        """Get employee by telegram_id and organization_id.

        Args:
            telegram_id: Telegram user ID.
            organization_id: Organization ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        return await self.repository.get_by_telegram_id_and_organization_id(
            telegram_id, organization_id
        )

