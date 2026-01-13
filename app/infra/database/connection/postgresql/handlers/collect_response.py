"""Collect response from aiopg and convert it to an annotated model."""

from functools import wraps
from typing import Any, List, Type, Union

from asyncpg.protocol import Record
from pydantic import TypeAdapter

from app.infra.database.postgresql.handlers.handle_exception import (
    handle_exception,
)
from unipkg.models.base import Model
from unipkg.models.exceptions import EmptyResult

__all__ = ["collect_response"]

_type_adapter_cache: dict[Any, TypeAdapter] = {}


def collect_response(fn):
    """Convert response from aiopg to an annotated model.

    Args:
        fn:
            Target function that contains a query in postgresql.

    Warnings:
        The function must return a single row or a list of rows in format like::

            >>> ({"key": "value"}, ...)

    Returns:
        The model that is specified in type hints of `fn`.

    Raises:
        EmptyResult: when a query of `fn` returns None.
    """

    @wraps(fn)
    @handle_exception
    async def inner(
        *args: object,
        **kwargs: object,
    ) -> Union[List[Type[Model]], Type[Model]]:
        """Inner function of :func:`.collect_response`. Convert response from
        aiopg to an annotated model.

        Args:
            *args:
                Positional arguments.
            **kwargs:
                Keyword arguments.

        Raises:
            EmptyResult: when a query of `fn` returns None.

        Returns:
            The model that is specified in type hints of `fn`.
        """

        response = await fn(*args, **kwargs)
        if not response:
            raise EmptyResult

        ann = fn.__annotations__["return"]

        if is_simple_type(ann):
            return response[0] if response else None

        # Use cached TypeAdapter for better performance
        if ann not in _type_adapter_cache:
            _type_adapter_cache[ann] = TypeAdapter(ann)

        adapter = _type_adapter_cache[ann]
        converted_data = __convert_response(response)

        return adapter.validate_python(converted_data)

    return inner


def is_simple_type(annotation: Any) -> bool:
    """Check if annotation is a simple type that doesn't need conversion."""
    return annotation in (int, str, float, bool, type(None))


def __convert_response(response_data: Union[Record, List[Record]]) -> Union[dict, List[dict]]:
    """Convert asyncpg Record(s) to dict(s) efficiently.

    Args:
        response_data: Single Record or list of Records.

    Returns:
        Single dict or list of dicts.
    """
    if isinstance(response_data, List):
        return [dict(record) for record in response_data]
    return dict(response_data)
