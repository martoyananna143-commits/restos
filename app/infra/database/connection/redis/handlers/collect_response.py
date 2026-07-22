"""Collect response from Redis and convert it to an annotated model."""

import orjson
from functools import wraps
from typing import Dict, List, Type, Union, get_origin

from pydantic import TypeAdapter

from unipkg.database.postgresql.handlers.handle_exception import (
    handle_exception,
)
from unipkg.models.base import Model
from unipkg.models.exceptions import EmptyResult

__all__ = ["collect_response"]

# Cache for TypeAdapter instances
_type_adapter_cache: dict[Type, TypeAdapter] = {}


def collect_response(fn):
    """Convert response from Redis to an annotated model."""
    
    @wraps(fn)
    @handle_exception
    async def inner(
        *args: object,
        **kwargs: object,
    ) -> Union[List[Type[Model]], Type[Model]]:
        response = await fn(*args, **kwargs)
        if not response:
            raise EmptyResult

        result_model = kwargs.get("result_model")
        if not result_model:
            return response

        converted_data = __convert_response(response, result_model)

        # Use cached TypeAdapter for better performance
        if result_model not in _type_adapter_cache:
            _type_adapter_cache[result_model] = TypeAdapter(result_model)
        
        adapter = _type_adapter_cache[result_model]
        return adapter.validate_python(converted_data)
    
    return inner


def load_json(raw_str: str) -> Dict:
    """Load JSON string into a dictionary (synchronous for better performance)."""
    try:
        return orjson.loads(fix_json_syntax(raw_str))
    except orjson.JSONDecodeError as e:
        raise ValueError("Invalid JSON format in response") from e


def handle_list(data: Union[List[bytes], bytearray], ann_type: Type) -> List[Dict]:
    """Handle list of bytes/bytearray and convert to list of dicts."""
    is_list = get_origin(ann_type) is list
    if not is_list:
        return []

    # Decode bytes to strings if needed
    if isinstance(data, list) and data and isinstance(data[0], bytes):
        data = [item.decode('utf-8') for item in data]

    if not isinstance(data, list):
        loaded_data = load_json(data)
        converted = __convert_memory_viewer(loaded_data)
        return [converted]
    
    # Use list comprehension for better performance
    return [
        __convert_memory_viewer(load_json(row))
        for row in data
    ]


def __convert_response(
    response: Union[bytes, bytearray, str, List],
    ann_type: Type,
) -> Union[List[Dict], Dict]:
    """Convert Redis response to dict(s) efficiently."""
    if isinstance(response, (bytearray, list)):
        return handle_list(response, ann_type)
    elif isinstance(response, bytes):
        response = response.decode('utf-8')

    if isinstance(response, str):
        loaded = load_json(response)
        return __convert_memory_viewer(loaded)
    
    raise ValueError(f"Invalid response type: {type(response)}")


def __convert_memory_viewer(data: Dict) -> Dict:
    """Convert memoryview and decode escaped strings."""
    for key, value in data.items():
        if isinstance(value, memoryview):
            data[key] = bytes(value).decode('utf-8', errors='ignore')
        elif isinstance(value, str) and '\\x' in value:
            try:
                decoded = (
                    bytes(value, 'latin-1')
                    .decode('unicode_escape')
                    .encode('latin-1')
                    .decode('utf-8')
                )
                data[key] = decoded
            except (UnicodeDecodeError, UnicodeError):
                pass
    return data


def fix_json_syntax(raw_str: str) -> str:
    """Fix Python-style JSON syntax to valid JSON."""
    return (
        raw_str
        .replace("'", '"')
        .replace("True", "true")
        .replace("False", "false")
        .replace("None", "null")
    )
