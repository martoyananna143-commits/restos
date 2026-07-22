"""Employee repository implementation using asyncpg and buildpg."""

import json
from typing import Any, Optional

from buildpg.asyncpg import BuildPgPool

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.employee.dto import (
    CreateEmployeeDTO,
    EmployeeDTO,
    UpdateEmployeeDTO,
)


class EmployeeRepositoryAsyncpg:
    """Repository for Employee model using asyncpg and buildpg."""

    def __init__(self, pool: BuildPgPool):
        """Initialize repository with database pool.

        Args:
            pool: PostgreSQL connection pool.
        """
        self._pool = pool

    @staticmethod
    def _normalize_meta(meta_raw: Any) -> dict:
        """Normalize meta field from database to dict.

        Args:
            meta_raw: Raw meta value from database (can be dict, str, or None).

        Returns:
            Normalized dict (empty dict if None or empty string).
        """
        if meta_raw is None:
            return {}
        if isinstance(meta_raw, str):
            return json.loads(meta_raw) if meta_raw else {}
        if isinstance(meta_raw, dict):
            return meta_raw
        return {}

    async def get_all(self) -> list[EmployeeDTO]:
        """Get all employees across all organizations.

        Returns:
            List of EmployeeDTO instances.
        """
        async with get_connection(self._pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE deleted_at IS NULL
                ORDER BY organization_id ASC, created_at DESC
                """,
            )

            return [
                EmployeeDTO(
                    id=row["id"],
                    telegram_id=row["telegram_id"],
                    employee_type_id=row["employee_type_id"],
                    organization_id=row["organization_id"],
                    full_name=row["full_name"],
                    username=row["username"],
                    phone=row["phone"],
                    position=row["position"],
                    hire_date=row["hire_date"],
                    is_active=row["is_active"],
                    meta=self._normalize_meta(row["meta"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_organization_id(self, organization_id: int) -> list[EmployeeDTO]:
        """Get all employees by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            List of EmployeeDTO instances.
        """

        async with get_connection(self._pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE organization_id = :organization_id AND deleted_at IS NULL
                ORDER BY created_at DESC
                """,
                organization_id=organization_id,
            )

            return [
                EmployeeDTO(
                    id=row["id"],
                    telegram_id=row["telegram_id"],
                    employee_type_id=row["employee_type_id"],
                    organization_id=row["organization_id"],
                    full_name=row["full_name"],
                    username=row["username"],
                    phone=row["phone"],
                    position=row["position"],
                    hire_date=row["hire_date"],
                    is_active=row["is_active"],
                    meta=self._normalize_meta(row["meta"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_id(self, employee_id: int) -> Optional[EmployeeDTO]:
        """Get employee by ID.

        Args:
            employee_id: Employee ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        async with get_connection(self._pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE id = :employee_id AND deleted_at IS NULL
                """,
                employee_id=employee_id,
            )

            if not row:
                return None

            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=self._normalize_meta(row["meta"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[EmployeeDTO]:
        """Get employee by telegram_id with employee_type code.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        async with get_connection(self._pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    e.id, e.telegram_id, e.employee_type_id, e.organization_id,
                    e.full_name, e.username, e.phone, e.position, e.hire_date,
                    e.is_active, e.meta, e.created_at, e.updated_at, e.deleted_at,
                    et.code as employee_type_code
                FROM employees e
                INNER JOIN employee_types et ON e.employee_type_id = et.id
                WHERE e.telegram_id = :telegram_id 
                    AND e.deleted_at IS NULL
                    AND e.is_active = true
                ORDER BY e.created_at DESC
                LIMIT 1
                """,
                telegram_id=telegram_id,
            )

            if not row:
                return None

            # Store employee_type_code in meta for easy access
            meta = self._normalize_meta(row["meta"])
            meta["employee_type_code"] = row["employee_type_code"]

            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=meta,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def get_by_telegram_id_and_organization_id(
        self, telegram_id: int, organization_id: int
    ) -> Optional[EmployeeDTO]:
        """Get employee by telegram_id and organization_id with employee_type code.

        Args:
            telegram_id: Telegram user ID.
            organization_id: Organization ID.

        Returns:
            EmployeeDTO if found, None otherwise.
        """
        async with get_connection(self._pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    e.id, e.telegram_id, e.employee_type_id, e.organization_id,
                    e.full_name, e.username, e.phone, e.position, e.hire_date,
                    e.is_active, e.meta, e.created_at, e.updated_at, e.deleted_at,
                    et.code as employee_type_code
                FROM employees e
                INNER JOIN employee_types et ON e.employee_type_id = et.id
                WHERE e.telegram_id = :telegram_id 
                    AND e.organization_id = :organization_id
                    AND e.deleted_at IS NULL
                    AND e.is_active = true
                LIMIT 1
                """,
                telegram_id=telegram_id,
                organization_id=organization_id,
            )

            if not row:
                return None

            # Store employee_type_code in meta for easy access
            meta = self._normalize_meta(row["meta"])
            meta["employee_type_code"] = row["employee_type_code"]

            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=meta,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def create(self, dto: CreateEmployeeDTO) -> EmployeeDTO:
        """Create a new employee.

        Args:
            dto: CreateEmployeeDTO with employee data.

        Returns:
            Created EmployeeDTO instance.
        """
        async with get_connection(self._pool) as conn:
            row = await conn.fetchrow_b(
                """
                INSERT INTO employees (
                    telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta
                )
                VALUES (
                    :telegram_id, :employee_type_id, :organization_id,
                    :full_name, :username, :phone, :position, :hire_date,
                    :is_active, :meta
                )
                RETURNING
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                """,
                telegram_id=dto.telegram_id,
                employee_type_id=dto.employee_type_id,
                organization_id=dto.organization_id,
                full_name=dto.full_name,
                username=dto.username,
                phone=dto.phone,
                position=dto.position,
                hire_date=dto.hire_date,
                is_active=dto.is_active,
                meta=json.dumps(dto.meta or {}),
            )

            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=self._normalize_meta(row["meta"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

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
        # Check if there are any fields to update
        has_updates = any(
            [
                dto.employee_type_id is not None,
                dto.organization_id is not None,
                dto.full_name is not None,
                dto.username is not None,
                dto.phone is not None,
                dto.position is not None,
                dto.hire_date is not None,
                dto.telegram_id is not None,
                dto.is_active is not None,
                dto.meta is not None,
            ]
        )

        if not has_updates:
            return await self.get_by_id(employee_id)

        async with get_connection(self._pool) as conn:
            # Build SET clause manually for fetchrow_b
            set_parts = []
            if dto.employee_type_id is not None:
                set_parts.append("employee_type_id = :employee_type_id")
            if dto.organization_id is not None:
                set_parts.append("organization_id = :organization_id")
            if dto.full_name is not None:
                set_parts.append("full_name = :full_name")
            if dto.username is not None:
                set_parts.append("username = :username")
            if dto.phone is not None:
                set_parts.append("phone = :phone")
            if dto.position is not None:
                set_parts.append("position = :position")
            if dto.hire_date is not None:
                set_parts.append("hire_date = :hire_date")
            if dto.telegram_id is not None:
                set_parts.append("telegram_id = :telegram_id")
            if dto.is_active is not None:
                set_parts.append("is_active = :is_active")
            if dto.meta is not None:
                set_parts.append("meta = :meta")
            set_parts.append("updated_at = NOW()")

            set_clause = ", ".join(set_parts)

            # Build parameters dict for fetchrow_b
            update_params: dict[str, Any] = {}
            if dto.employee_type_id is not None:
                update_params["employee_type_id"] = dto.employee_type_id
            if dto.organization_id is not None:
                update_params["organization_id"] = dto.organization_id
            if dto.full_name is not None:
                update_params["full_name"] = dto.full_name
            if dto.username is not None:
                update_params["username"] = dto.username
            if dto.phone is not None:
                update_params["phone"] = dto.phone
            if dto.position is not None:
                update_params["position"] = dto.position
            if dto.hire_date is not None:
                update_params["hire_date"] = dto.hire_date
            if dto.telegram_id is not None:
                update_params["telegram_id"] = dto.telegram_id
            if dto.is_active is not None:
                update_params["is_active"] = dto.is_active
            if dto.meta is not None:
                update_params["meta"] = json.dumps(dto.meta) if dto.meta else "{}"
            update_params["employee_id"] = employee_id

            # Use fetchrow_b with named parameters directly
            row = await conn.fetchrow_b(
                f"""
                UPDATE employees
                SET {set_clause}
                WHERE id = :employee_id AND deleted_at IS NULL
                RETURNING
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                """,
                **update_params,
            )

            if not row:
                return None

            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=self._normalize_meta(row["meta"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def delete(self, employee_id: int) -> bool:
        """Soft delete employee.

        Args:
            employee_id: Employee ID.

        Returns:
            True if deleted, False otherwise.
        """
        async with get_connection(self._pool) as conn:
            result = await conn.execute_b(
                """
                UPDATE employees
                SET deleted_at = NOW(), updated_at = NOW()
                WHERE id = :employee_id AND deleted_at IS NULL
                """,
                employee_id=employee_id,
            )

            # execute_b returns a string like "UPDATE 1" or "UPDATE 0"
            return result and "UPDATE 1" in str(result)

    async def restore(self, employee_id: int) -> bool:
        """Restore soft-deleted employee.

        Args:
            employee_id: Employee ID.

        Returns:
            True if restored, False otherwise.
        """
        async with get_connection(self._pool) as conn:
            result = await conn.execute_b(
                """
                UPDATE employees
                SET deleted_at = NULL, updated_at = NOW()
                WHERE id = :employee_id AND deleted_at IS NOT NULL
                """,
                employee_id=employee_id,
            )

            # execute_b returns a string like "UPDATE 1" or "UPDATE 0"
            return result and "UPDATE 1" in str(result)

    async def get_by_organization_id_with_deleted(
        self, organization_id: int
    ) -> list[EmployeeDTO]:
        """Get all employees by organization ID including deleted ones."""
        async with get_connection(self._pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE organization_id = :organization_id
                ORDER BY deleted_at NULLS FIRST, created_at DESC
                """,
                organization_id=organization_id,
            )
            return [
                EmployeeDTO(
                    id=row["id"],
                    telegram_id=row["telegram_id"],
                    employee_type_id=row["employee_type_id"],
                    organization_id=row["organization_id"],
                    full_name=row["full_name"],
                    username=row["username"],
                    phone=row["phone"],
                    position=row["position"],
                    hire_date=row["hire_date"],
                    is_active=row["is_active"],
                    meta=self._normalize_meta(row["meta"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_web_login(self, login: str) -> Optional[EmployeeDTO]:
        """Get employee by web_login stored in meta JSONB."""
        async with get_connection(self._pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE meta->>'web_login' = :login AND deleted_at IS NULL
                LIMIT 1
                """,
                login=login,
            )
            if not row:
                return None
            return EmployeeDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                employee_type_id=row["employee_type_id"],
                organization_id=row["organization_id"],
                full_name=row["full_name"],
                username=row["username"],
                phone=row["phone"],
                position=row["position"],
                hire_date=row["hire_date"],
                is_active=row["is_active"],
                meta=self._normalize_meta(row["meta"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def get_all_by_web_login(self, login: str) -> list[EmployeeDTO]:
        """Get all employees (across all orgs) that share the same web_login."""
        async with get_connection(self._pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, telegram_id, employee_type_id, organization_id,
                    full_name, username, phone, position, hire_date,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM employees
                WHERE meta->>'web_login' = :login AND deleted_at IS NULL
                ORDER BY organization_id
                """,
                login=login,
            )
            return [
                EmployeeDTO(
                    id=row["id"],
                    telegram_id=row["telegram_id"],
                    employee_type_id=row["employee_type_id"],
                    organization_id=row["organization_id"],
                    full_name=row["full_name"],
                    username=row["username"],
                    phone=row["phone"],
                    position=row["position"],
                    hire_date=row["hire_date"],
                    is_active=row["is_active"],
                    meta=self._normalize_meta(row["meta"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def update_meta(self, employee_id: int, meta: dict) -> bool:
        """Update employee meta JSONB field."""
        async with get_connection(self._pool) as conn:
            result = await conn.execute_b(
                """
                UPDATE employees
                SET meta = :meta::jsonb, updated_at = NOW()
                WHERE id = :employee_id AND deleted_at IS NULL
                """,
                meta=json.dumps(meta),
                employee_id=employee_id,
            )
            return result and "UPDATE 1" in str(result)

    async def get_employee_types(self) -> list[dict]:
        """Get all available employee types."""
        async with get_connection(self._pool) as conn:
            rows = await conn.fetch(
                "SELECT id, name, code, is_administrator FROM employee_types ORDER BY id"
            )
            return [dict(row) for row in rows]