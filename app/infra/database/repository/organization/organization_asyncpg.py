"""Organization repository implementation using asyncpg and buildpg."""

from typing import Any, Awaitable, Optional, Union

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.organization.dto import (
    CreateOrganizationDTO,
    OrganizationDTO,
    UpdateOrganizationDTO,
)


class OrganizationRepositoryAsyncpg:
    """Repository for Organization model using asyncpg and buildpg."""

    def __init__(self, pool: Union[BuildPgPool, Awaitable[BuildPgPool], Any]):
        """Initialize repository with database pool.

        Args:
            pool: PostgreSQL connection pool, awaitable, or Resource provider.
        """
        self._pool = pool
        self._resolved_pool: Optional[BuildPgPool] = None

    async def _get_pool(self) -> BuildPgPool:
        """Get resolved pool, awaiting if necessary.

        Returns:
            Resolved BuildPgPool instance.
        """
        if self._resolved_pool is None:
            # Check if it's already a BuildPgPool
            if isinstance(self._pool, BuildPgPool):
                self._resolved_pool = self._pool
            # Check if it's a Resource provider
            elif isinstance(self._pool, providers.Resource):
                # Resource provider automatically resolves when accessed
                self._resolved_pool = await self._pool()
            # Check if it's a bound method (from postgresql_resource.provided)
            elif hasattr(self._pool, "__self__") and hasattr(self._pool, "__func__"):
                # This is a bound method, we need to get the Resource provider from container
                from app.internal import Container

                container = Container()
                # Get the resource provider and await it
                resource_provider = container.postgresql_resource
                self._resolved_pool = await resource_provider()
            # Check if it's an awaitable (coroutine)
            elif hasattr(self._pool, "__await__"):
                self._resolved_pool = await self._pool
            else:
                raise TypeError(f"Cannot resolve pool: {type(self._pool)}")
        return self._resolved_pool

    async def get_by_user_telegram_id(
        self, telegram_id: int
    ) -> Optional[OrganizationDTO]:
        """Get first organization by user telegram_id (through employee relationship).

        Args:
            telegram_id: User telegram ID.

        Returns:
            OrganizationDTO if found, None otherwise.
        """
        organizations = await self.get_all_by_user_telegram_id(telegram_id)
        return organizations[0] if organizations else None

    async def get_all_by_user_telegram_id(
        self, telegram_id: int
    ) -> list[OrganizationDTO]:
        """Get all organizations by user telegram_id (through employee relationship).

        Args:
            telegram_id: User telegram ID.

        Returns:
            List of OrganizationDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT DISTINCT
                    o.id, o.name, o.code, o.address, o.phone,
                    o.is_active, o.meta, o.created_at, o.updated_at, o.deleted_at
                FROM organizations o
                INNER JOIN employees e ON e.organization_id = o.id
                WHERE e.telegram_id = :telegram_id
                    AND o.deleted_at IS NULL
                    AND e.deleted_at IS NULL
                ORDER BY o.created_at DESC
                """,
                telegram_id=telegram_id,
            )

            return [
                OrganizationDTO(
                    id=row["id"],
                    name=row["name"],
                    code=row["code"],
                    address=row["address"],
                    phone=row["phone"],
                    is_active=row["is_active"],
                    meta=row["meta"] or {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_all(self) -> list[OrganizationDTO]:
        """Get all organizations.

        Returns:
            List of OrganizationDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, name, code, address, phone,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM organizations
                WHERE deleted_at IS NULL
                ORDER BY name ASC
                """,
            )

            return [
                OrganizationDTO(
                    id=row["id"],
                    name=row["name"],
                    code=row["code"],
                    address=row["address"],
                    phone=row["phone"],
                    is_active=row["is_active"],
                    meta=row["meta"] or {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_id(self, organization_id: int) -> Optional[OrganizationDTO]:
        """Get organization by ID.

        Args:
            organization_id: Organization ID.

        Returns:
            OrganizationDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, name, code, address, phone,
                    is_active, meta, created_at, updated_at, deleted_at
                FROM organizations
                WHERE id = :organization_id AND deleted_at IS NULL
                """,
                organization_id=organization_id,
            )

            if not row:
                return None

            return OrganizationDTO(
                id=row["id"],
                name=row["name"],
                code=row["code"],
                address=row["address"],
                phone=row["phone"],
                is_active=row["is_active"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def create(self, dto: CreateOrganizationDTO) -> OrganizationDTO:
        """Create a new organization.

        Args:
            dto: CreateOrganizationDTO with organization data.

        Returns:
            Created OrganizationDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                INSERT INTO organizations (
                    name, code, address, phone, is_active, meta
                )
                VALUES (
                    :name, :code, :address, :phone, :is_active, :meta
                )
                RETURNING
                    id, name, code, address, phone,
                    is_active, meta, created_at, updated_at, deleted_at
                """,
                name=dto.name,
                code=dto.code,
                address=dto.address,
                phone=dto.phone,
                is_active=dto.is_active,
                meta=str(dto.meta or {}),
            )

            return OrganizationDTO(
                id=row["id"],
                name=row["name"],
                code=row["code"],
                address=row["address"],
                phone=row["phone"],
                is_active=row["is_active"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

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
        # Check if there are any fields to update
        has_updates = any(
            [
                dto.name is not None,
                dto.code is not None,
                dto.address is not None,
                dto.phone is not None,
                dto.is_active is not None,
                dto.meta is not None,
            ]
        )

        if not has_updates:
            return await self.get_by_id(organization_id)

        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Build SET clause manually for fetchrow_b
            set_parts = []
            if dto.name is not None:
                set_parts.append("name = :name")
            if dto.code is not None:
                set_parts.append("code = :code")
            if dto.address is not None:
                set_parts.append("address = :address")
            if dto.phone is not None:
                set_parts.append("phone = :phone")
            if dto.is_active is not None:
                set_parts.append("is_active = :is_active")
            if dto.meta is not None:
                set_parts.append("meta = :meta")
            set_parts.append("updated_at = NOW()")

            set_clause = ", ".join(set_parts)

            # Build parameters dict for fetchrow_b
            update_params: dict[str, Any] = {}
            if dto.name is not None:
                update_params["name"] = dto.name
            if dto.code is not None:
                update_params["code"] = dto.code
            if dto.address is not None:
                update_params["address"] = dto.address
            if dto.phone is not None:
                update_params["phone"] = dto.phone
            if dto.is_active is not None:
                update_params["is_active"] = dto.is_active
            if dto.meta is not None:
                update_params["meta"] = dto.meta
            update_params["organization_id"] = organization_id

            # Use fetchrow_b with named parameters directly
            row = await conn.fetchrow_b(
                f"""
                UPDATE organizations
                SET {set_clause}
                WHERE id = :organization_id AND deleted_at IS NULL
                RETURNING
                    id, name, code, address, phone,
                    is_active, meta, created_at, updated_at, deleted_at
                """,
                **update_params,
            )

            if not row:
                return None

            return OrganizationDTO(
                id=row["id"],
                name=row["name"],
                code=row["code"],
                address=row["address"],
                phone=row["phone"],
                is_active=row["is_active"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )
