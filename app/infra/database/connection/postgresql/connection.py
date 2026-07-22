"""Create connection to postgresql."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import orjson
from buildpg import asyncpg
from buildpg.asyncpg import BuildPgPool

__all__ = ["_get_connection", "acquire_connection"]


@asynccontextmanager
async def _get_connection(
    pool: Optional[BuildPgPool],
    return_pool: bool = False,
) -> AsyncGenerator[asyncpg.BuildPgConnection, BuildPgPool]:
    """Get async connection pool to PostgreSQL.
    
    Args:
        pool:
            PostgreSQL connection pool.
        return_pool:
            if True, return pool, else return connection.
            
    Examples:
        If you have a function that contains a query in PostgreSQL,
        context manager :func:`.get_connection`
        will get async connection to PostgreSQL
        of pool::
            >>> async def exec_some_sql_function() -> None:
            ...     async with get_connection() as conn:
            ...         await conn.execute("SELECT * FROM users")
            
    Returns:
        Async connection to PostgreSQL.
    """

    if not isinstance(pool, BuildPgPool):
        pool = await pool
    if return_pool:
        yield pool
        return
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def acquire_connection(
    pool: BuildPgPool,
    cursor_factory: Optional[bool] = True,
) -> asyncpg.BuildPgConnection:
    """Acquire connection from pool with optimized JSON codec setup.
    
    Args:
        pool:
            PostgreSQL connection pool from :func:`.get_connection`.
        cursor_factory:
            If True, setup JSON codec for dictionary-like records.
            
    Examples:
        If you have a function that contains a query in PostgreSQL,
        context manager :func:`.acquire_connection`
        will get async connection to PostgreSQL
        of pool::
            >>> async def exec_some_sql_function() -> None:
            ...     q = "SELECT * FROM users;"
            ...     async with get_connection(return_pool=True) as __pool:
            ...         async with acquire_connection(__pool) as conn:
            ...             await conn.fetch(q)
            
    Returns:
        Async connection to PostgreSQL.
    """

    async with pool.acquire() as conn:
        if cursor_factory:
            await conn.set_type_codec(
                "json",
                encoder=lambda value: orjson.dumps(value),
                decoder=lambda value: orjson.loads(value),
                schema="pg_catalog",
            )
        yield conn
