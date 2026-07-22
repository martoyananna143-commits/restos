"""Handle Redis Query Exceptions."""

from typing import Callable

from redis.asyncio import RedisError

from unipkg.logger import Logger
from unipkg.models.base import Model
from unipkg.models.exceptions import DriverError, EmptyResult

logger = Logger().get_logger(__name__, need_file_handler=False)

__all__ = ["handle_exception"]


def handle_exception(func: Callable[..., Model]):
    """Decorator Catching Postgresql Query Exceptions.

    Args:
        func:
            callable function object.

    Returns:
        Result of call function.

    Raises:
        DriverError: Any error during execution query on a database.
    """

    async def wrapper(*args: object, **kwargs: object) -> Model:
        """Inner function. Catching Redis Query Exceptions.

        Args:
            *args:
                Positional arguments.
            **kwargs:
                Keyword arguments.

        Raises:
            DriverError: Any error during execution query in database.

        Returns:
            Result of call function.
        """

        try:
            return await func(*args, **kwargs)
        except EmptyResult as ex:
            raise EmptyResult from ex
        except RedisError as error:
            raise error
        except Exception as ex:
            logger.critical("Error while executing query: %s", ex)
            raise DriverError from ex

    return wrapper
