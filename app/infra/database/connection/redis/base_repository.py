"""
Redis repository module.

This module provides a base repository class for interacting with a Redis database.
It includes methods for creating, reading, and deleting data in Redis, 
as well as handling exceptions and collecting responses.

Classes:
    BaseRedisRepository: A base repository class for Redis operations.

Usage example:
    repository = BaseRedisRepository()
    await repository.create("key", "value", expire_time=3600)
    value = await repository.read("key", MyModel)
    await repository.delete("key")
"""

from typing import List, Optional, Type, TypeVar

from unipkg.models.base import BaseModel

from .connection import _get_connection
from .handlers import (
    collect_response,
    handle_exception,
)

__all__ = ["BaseRedisRepository"]

BaseRepository = TypeVar("BaseRepository", bound="BaseRedisRepository")


class BaseRedisRepository:
    """Repository for alert manager system."""

    def __init__(self, redis_connection):
        self.redis_connection = redis_connection

    @handle_exception
    async def create(
        self,
        redis_key: str,
        redis_value: str,
        expire_time: Optional[int] = None,
    ):
        async with self.redis_connection() as connect:
            await connect.set(redis_key, redis_value)
            if expire_time:
                await connect.expire(redis_key, expire_time)

    @collect_response
    async def read(
        self,
        redis_key: str,
        result_model: Type[BaseModel],  # pylint: disable=unused-argument
    ) -> Type[BaseModel]:
        async with self.redis_connection() as connect:
            return await connect.get(redis_key)

    @collect_response
    async def read_all(
        self,
        result_model: List[Type[BaseModel]],  # pylint: disable=unused-argument
    ) -> List[Type[BaseModel]]:
        async with self.redis_connection() as connect:
            cursor = b'0'
            keys = []
            values = []
            while True:
                cursor, batch_keys = await connect.scan(cursor)
                keys.extend(batch_keys)
                if not cursor:
                    break
            for key in keys:
                value = await connect.get(key)
                values.append(value)
            return values

    @handle_exception
    async def delete(
        self,
        redis_key: str,
    ):
        async with self.redis_connection() as connect:
            await connect.delete(redis_key)

    @handle_exception
    async def delete_many(
        self,
        redis_keys: List[int],
    ):
        async with self.redis_connection() as connect:
            await connect.delete(*redis_keys)
