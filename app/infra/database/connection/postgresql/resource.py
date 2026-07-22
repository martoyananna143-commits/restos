"""Async resource for PostgresSQL connector."""

from typing import Optional

from buildpg import asyncpg

from ..resources import BaseAsyncResource

__all__ = ["Postgresql"]


class Postgresql(BaseAsyncResource):
    """PostgreSQL connector using asyncpg."""

    async def init(
        self,
        dsn: str,
        min_size: int = 5,
        max_size: int = 10,
        max_queries: int = 50000,
        max_inactive_connection_lifetime: float = 300.0,
        command_timeout: float = 60.0,
        *args,
        **kwargs,
    ) -> Optional[asyncpg.BuildPgPool]:
        """Getting connection pool asynchronously.

        Args:
            dsn: D.S.N - Data Source Name.
            min_size: Minimum number of connections in the pool.
            max_size: Maximum number of connections in the pool.
            max_queries: Maximum number of queries per connection before recycling.
            max_inactive_connection_lifetime: Maximum idle time for connections (seconds).
            command_timeout: Command timeout in seconds.

        Returns:
            Created connection pool.
        """

        return await asyncpg.create_pool_b(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            max_queries=max_queries,
            max_inactive_connection_lifetime=max_inactive_connection_lifetime,
            command_timeout=command_timeout,
            *args,
            **kwargs,
        )

    async def shutdown(self, resource: asyncpg.BuildPgPool):
        """Close connection.

        Args:
            resource: Resource returned by :meth:`.Postgresql.init()` method.

        Notes:
            This method is called automatically
            when the application is stopped
            or
            ``Closing`` provider is used.
        """

        await resource.close()
