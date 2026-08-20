"""Reviewed source and Wave A manifest contract tests."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.internal.services.assessment_template_import_service import (
    AssessmentTemplateImportError,
    ReviewedManifest,
)


ROOT = Path(__file__).parents[1]
DATA = ROOT / "app/internal/data/assessment_template_import"
EXPECTED_COUNTS = {
    "bar-practicum.json": (1, 13),
    "cook-kln.json": (4, 15),
    "hostess-kln.json": (4, 39),
    "itci-kln.json": (7, 30),
    "kitchen-practicum.json": (1, 13),
    "production-walkthrough.json": (11, 199),
    "restaurant-service-walkthrough.json": (17, 117),
    "waiter-kln.json": (4, 43),
}
EXPECTED_SOURCES = {
    "_Оценка вкуса и скорости_Дебри.xlsx": "5dc8d0f7d9a3f1bd748bad19cba312533106629b5af3fcf6028740e2c9407436",
    "Бланк аналитики отзывов общий 2026.xlsx": "a73781bf5a4eea18a6b85a72a705c28cfa656ebab4e615df063b1ff8ba87d94b",
    "КЛН повара_Камелот.xlsx": "6bdcdcb35a6003769552209e6439bb6c56f9ac968120da6bdeb650db592e064e",
    "КЛН Руководителей_Камелот.xlsx": "b19824ecac962517df729aa7270aca97ce77a191f211136e3e10007660e63c16",
    "НОВЫЙ ИСПРАВЛЕННЫЙ КЛН-корректировка официант - Камелот, новый .xlsx": "e0e34ffcb0304fc3db9f0c9b790acc8613d54cc76488ef1b2bba6d08b584048a",
    "SM, КЛН_ITCI,  Камелот - новый .xlsx": "43d2993f09a616ead491b412ef48ccc778392f786d9d4f45da17d4b59aaa33d9",
    "SM, Бланк оценки сервиса ресторана, Камелот - новый .xlsx": "13b24f5ebf320d7bc7ed2c0313dd99b8b0f44c8408ce688c7e3406f47dea8e4d",
    "НОВЫЙ ИСПРАВЛЕННЫЙ КЛН-корректировка хостес .xlsx": "065b9e74097bb7cdda55d3d36df7840b89d5c91bcaef226ab5f6abfabef80938",
    "БО производства WP_Дебри.xlsx": "933fca2cb9b9b8b043e2085c547193bc9af6b2fefbe2392f2abe1537238c15bd",
}


def manifests() -> list[tuple[Path, ReviewedManifest]]:
    return [
        (path, ReviewedManifest.parse(path.read_bytes()))
        for path in sorted((DATA / "manifests").glob("*.json"))
    ]


def test_source_inventory_fixes_exact_nine_read_only_provenances() -> None:
    inventory = json.loads((DATA / "source_inventory.json").read_text("utf-8"))
    assert inventory["schema_version"] == 1
    assert len(inventory["sources"]) == 9
    assert {
        value["filename"]: value["sha256"] for value in inventory["sources"]
    } == EXPECTED_SOURCES
    assert all(len(value["sha256"]) == 64 for value in inventory["sources"])
    assert {value["provenance"] for value in inventory["sources"]} == {
        "read_only_methodology_source"
    }
    assert not any(
        "/" in value["filename"] or "\\" in value["filename"]
        for value in inventory["sources"]
    )


def test_reviewed_manifests_have_exact_shape_and_counts() -> None:
    values = manifests()
    assert {path.name for path, _ in values} == set(EXPECTED_COUNTS)
    for path, manifest in values:
        sections = manifest.document["template"]["sections"]
        items = [item for section in sections for item in section["items"]]
        assert (len(sections), len(items)) == EXPECTED_COUNTS[path.name]
        assert all(item["metrics"] for item in items)
        assert all(item["response_type"] == "boolean" for item in items)
        assert (
            manifest.document["source"]["provenance"] == "read_only_methodology_source"
        )


def test_waiter_release_has_exact_equal_weight_contract() -> None:
    missing = {}
    for path, manifest in manifests():
        items = [
            item
            for section in manifest.document["template"]["sections"]
            for item in section["items"]
        ]
        missing[path.name] = sum(item["weight"] is None for item in items)
    assert missing == {
        "bar-practicum.json": 0,
        "cook-kln.json": 0,
        "hostess-kln.json": 0,
        "itci-kln.json": 0,
        "kitchen-practicum.json": 0,
        "production-walkthrough.json": 0,
        "restaurant-service-walkthrough.json": 0,
        "waiter-kln.json": 0,
    }
    waiter = next(
        manifest for path, manifest in manifests() if path.name == "waiter-kln.json"
    )
    items = [
        item
        for section in waiter.document["template"]["sections"]
        for item in section["items"]
    ]
    assert len(items) == 43
    assert {item["weight"] for item in items} == {"1.0"}
    assert {
        mapping["weight"] for item in items for mapping in item["metrics"]
    } == {"1.0"}
    assert {section["weight"] for section in waiter.document["template"]["sections"]} == {
        None
    }
    assert waiter.document["template"]["scoring"]["config"] == {
        "rounding": "half_up",
        "score_scale": 100,
        "weight_policy": "owner_equal_criterion_weights_v1",
        "criterion_weight": "1.0",
        "source_weights_used": False,
    }
    assert waiter.document["source"] == {
        "filename": "НОВЫЙ ИСПРАВЛЕННЫЙ КЛН-корректировка официант - Камелот, новый .xlsx",
        "sha256": "e0e34ffcb0304fc3db9f0c9b790acc8613d54cc76488ef1b2bba6d08b584048a",
        "provenance": "read_only_methodology_source",
    }
    decisions = {
        path.name: manifest.publication_ready() for path, manifest in manifests()
    }
    assert all(decisions.values())


def test_manifests_do_not_contain_historical_measurement_fields() -> None:
    forbidden_keys = {
        "employee_name",
        "evaluator_name",
        "historical_answers",
        "historical_comments",
        "phone",
        "account_id",
        "venue_name",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from keys(nested)

    assert all(
        forbidden_keys.isdisjoint(keys(manifest.document))
        for _, manifest in manifests()
    )


def test_manifest_rejects_unknown_metric_and_unknown_field() -> None:
    _, original = manifests()[0]
    invalid_metric = deepcopy(original.document)
    invalid_metric["template"]["sections"][0]["items"][0]["metrics"][0][
        "code"
    ] = "invented"
    with pytest.raises(AssessmentTemplateImportError, match="unknown metric"):
        ReviewedManifest.parse(json.dumps(invalid_metric).encode())

    extra = deepcopy(original.document)
    extra["source"]["local_path"] = "/private/source.xlsx"
    with pytest.raises(AssessmentTemplateImportError, match="fields"):
        ReviewedManifest.parse(json.dumps(extra).encode())


def test_manifest_hash_is_canonical_and_format_independent() -> None:
    _, original = manifests()[0]
    compact = json.dumps(original.document, ensure_ascii=False).encode()
    reordered = json.dumps(
        original.document, ensure_ascii=False, sort_keys=True, indent=4
    ).encode()
    assert (
        ReviewedManifest.parse(compact).manifest_sha256
        == ReviewedManifest.parse(reordered).manifest_sha256
    )
