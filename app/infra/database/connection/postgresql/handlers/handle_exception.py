"""Handle Postgresql Query Exceptions."""

from typing import Callable

from asyncpg.exceptions import PostgresError, UniqueViolationError

from unipkg.logger import Logger
from unipkg.models.base import Model
from unipkg.models.exceptions import DriverError, UniqueViolation

logger = Logger().get_logger(__name__, need_file_handler=False)

__all__ = ["handle_exception"]


def handle_exception(func: Callable[..., Model]):
    """Decorator Catching Postgresql Query Exceptions.

    Args:
        func:
            callable function object.

    Examples:
        If you have a function that contains a query in postgresql,
        decorator :func:`.handle_exception` will catch the exceptions that can be
        raised by the query::

            >>> from app.pkg import models
            >>> from app.internal.repository.postgresql.connection import get_connection
            >>> @handle_exception
            ... async def create(self, cmd: models.CreateUserRoleCommand) -> None:
            ...     q = \"""
            ...         insert into user_roles(role_name) values (%(role_name)s)
            ...         on conflict do nothing returning role_name;
            ...     \"""
            ...     async with get_connection() as cur:
            ...         await cur.execute(q, cmd.to_dict(show_secrets=True))

    Returns:
        Result of call function.

    Raises:
        UniqueViolation: The query violates the domain uniqueness constraints
            of the database set.
        DriverError: Any error during execution query on a database.
    """

    async def wrapper(*args: object, **kwargs: object) -> Model:
        """Inner function. Catching Postgresql Query Exceptions.

        Args:
            *args:
                Positional arguments.
            **kwargs:
                Keyword arguments.

        Raises:
            UniqueViolation: The query violates the domain uniqueness constraints
                of the database set.
            DriverError: Any error during execution query on an database.

        Returns:
            Result of call function.
        """

        try:
            return await func(*args, **kwargs)
        except PostgresError as error:
            if isinstance(error, UniqueViolationError):
                raise UniqueViolation from error

            logger.critical("Error while executing query: %s", error)
            raise DriverError(message=str(error)) from error

    return wrapper
