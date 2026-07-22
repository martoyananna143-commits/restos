"""Create connection to redis."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Union

from redis.asyncio import Connection, ConnectionPool, Redis


__all__ = ["_get_connection"]


@asynccontextmanager
async def _get_connection(
    pool: ConnectionPool,
    return_pool: bool = False,
) -> AsyncGenerator[Union[Connection, ConnectionPool], None]:
    """Get async connection pool to redis."""

    if not isinstance(pool, ConnectionPool):
        pool = await pool

    redis_client = Redis.from_pool(pool)

    if return_pool:
        yield pool
        return

    yield redis_client
