"""Focused contract tests for organization JSONB metadata normalization."""

from types import MappingProxyType

import pytest

from app.infra.database.repository.organization.organization_asyncpg import (
    normalize_organization_meta,
)


def test_none_normalizes_to_empty_object():
    assert normalize_organization_meta(None) == {}


def test_mapping_normalizes_to_detached_dict():
    source = {"marker": "value"}
    normalized = normalize_organization_meta(MappingProxyType(source))
    assert normalized == source
    assert normalized is not source


def test_json_object_string_normalizes_once():
    assert normalize_organization_meta('{"marker": "value"}') == {
        "marker": "value"
    }


@pytest.mark.parametrize(
    "value",
    ["not-json", "[]", '"scalar"', "1", b"{}"],
)
def test_invalid_metadata_is_rejected_without_disclosure(value):
    with pytest.raises(ValueError) as caught:
        normalize_organization_meta(value)
    assert str(caught.value) == "organization metadata is invalid"
    assert repr(value) not in str(caught.value)
