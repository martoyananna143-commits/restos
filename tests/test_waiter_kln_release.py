"""Release regressions for the approved equal-weight waiter KLN."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.database.models import (
    AssessmentItemMetricMapping,
    AssessmentMethodology,
    AssessmentScoringPolicy,
    AssessmentTemplate,
    AssessmentTemplateImportSource,
    AssessmentTemplateItem,
    AssessmentTemplateSection,
)
from app.internal.services.assessment_template_import_service import (
    AssessmentLibraryImportService,
    AssessmentTemplateImportError,
    ReviewedManifest,
)
from app.internal.services.assessment_weighted_scoring_service import (
    WeightedItem,
    calculate_weighted_result,
)


MANIFEST_PATH = (
    Path(__file__).parents[1]
    / "app/internal/data/assessment_template_import/manifests/waiter-kln.json"
)
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def waiter_manifest() -> ReviewedManifest:
    return ReviewedManifest.parse(MANIFEST_PATH.read_bytes())


def unique_waiter_manifest() -> ReviewedManifest:
    document = deepcopy(waiter_manifest().document)
    suffix = uuid4().hex[:12]
    document["template"]["code"] = f"waiter-kln-release-{suffix}"
    document["template"]["methodology"]["code"] = (
        f"waiter-kln-methodology-release-{suffix}"
    )
    return ReviewedManifest.parse(json.dumps(document, ensure_ascii=False).encode())


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    value = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield value
    finally:
        await value.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def test_equal_weight_manifest_scores_all_43_criteria_without_section_weights():
    manifest = waiter_manifest().document
    sections = manifest["template"]["sections"]
    item_documents = [item for section in sections for item in section["items"]]
    weighted_items = [
        WeightedItem(
            item_id=uuid4(),
            answer_type="boolean",
            required=True,
            weight=Decimal(item["weight"]),
            min_value=None,
            max_value=None,
            criticality=item["criticality"],
            config=item["config"],
            option_values={},
        )
        for item in item_documents
    ]

    all_yes = calculate_weighted_result(
        weighted_items, {item.item_id: True for item in weighted_items}
    )
    one_no = calculate_weighted_result(
        weighted_items,
        {
            item.item_id: index != 0
            for index, item in enumerate(weighted_items)
        },
    )
    all_no = calculate_weighted_result(
        weighted_items, {item.item_id: False for item in weighted_items}
    )
    representative_mixed = calculate_weighted_result(
        weighted_items,
        {
            item.item_id: index < 21
            for index, item in enumerate(weighted_items)
        },
    )
    optional_last = replace(weighted_items[-1], required=False)
    n_a_excluded = calculate_weighted_result(
        [*weighted_items[:-1], optional_last],
        {item.item_id: True for item in weighted_items[:-1]},
    )
    section_scores = []
    offset = 0
    for section in sections:
        section_items = weighted_items[offset : offset + len(section["items"])]
        section_scores.append(
            calculate_weighted_result(
                section_items,
                {item.item_id: True for item in section_items},
            ).score_percent
        )
        offset += len(section_items)

    assert len(sections) == 4
    assert len(weighted_items) == 43
    assert {section["weight"] for section in sections} == {None}
    assert all_yes.numerator == all_yes.denominator == Decimal("43.0")
    assert all_yes.score_percent == Decimal("100.0000")
    assert one_no.numerator == Decimal("42.0")
    assert one_no.denominator == Decimal("43.0")
    assert one_no.score_percent == Decimal("97.6744")
    assert all_no.numerator == Decimal("0.0")
    assert all_no.denominator == Decimal("43.0")
    assert all_no.score_percent == Decimal("0.0000")
    assert representative_mixed.numerator == Decimal("21.0")
    assert representative_mixed.denominator == Decimal("43.0")
    assert representative_mixed.score_percent == Decimal("48.8372")
    assert n_a_excluded.numerator == n_a_excluded.denominator == Decimal("42.0")
    assert n_a_excluded.score_percent == Decimal("100.0000")
    assert n_a_excluded.coverage == Decimal("0.976744")
    assert n_a_excluded.excluded_count == 1
    assert section_scores == [Decimal("100.0000")] * 4


@pytest.mark.asyncio
async def test_library_dry_run_apply_and_repeat_persist_exact_waiter_contract(session):
    manifest = unique_waiter_manifest()
    importer = AssessmentLibraryImportService(session)

    plan = await importer.plan(manifest)
    assert plan.action == "create"
    assert plan.template_code == manifest.document["template"]["code"]
    assert plan.next_version == 1
    assert plan.section_count == 4
    assert plan.item_count == 43

    created = await importer.apply(manifest, NOW)
    repeated = await importer.apply(manifest, NOW)
    assert created.action == "create"
    assert repeated.action == "no_op"
    assert repeated.template_id == created.template_id
    assert repeated.template_version_id == created.template_version_id
    assert created.version == 1

    item_weights = (
        await session.execute(
            select(AssessmentTemplateItem.weight).where(
                AssessmentTemplateItem.template_version_id
                == created.template_version_id
            )
        )
    ).scalars().all()
    section_weights = (
        await session.execute(
            select(AssessmentTemplateSection.weight).where(
                AssessmentTemplateSection.template_version_id
                == created.template_version_id
            )
        )
    ).scalars().all()
    mapping_weights = (
        await session.execute(
            select(AssessmentItemMetricMapping.contribution_weight).where(
                AssessmentItemMetricMapping.template_version_id
                == created.template_version_id
            )
        )
    ).scalars().all()
    policy = await session.get(AssessmentScoringPolicy, created.template_version_id)
    source = await session.scalar(
        select(AssessmentTemplateImportSource).where(
            AssessmentTemplateImportSource.template_version_id
            == created.template_version_id
        )
    )

    assert len(item_weights) == 43 and set(item_weights) == {Decimal("1.0")}
    assert len(section_weights) == 4 and set(section_weights) == {None}
    assert mapping_weights and set(mapping_weights) == {Decimal("1.0")}
    assert policy is not None and policy.algorithm == "weighted_v1"
    assert policy.config["weight_policy"] == "owner_equal_criterion_weights_v1"
    assert policy.config["source_weights_used"] is False
    assert source is not None
    assert source.source_filename == manifest.document["source"]["filename"]
    assert source.source_sha256.hex() == manifest.document["source"]["sha256"]


@pytest.mark.asyncio
async def test_invalid_waiter_manifest_has_no_partial_library_state(session):
    invalid = deepcopy(waiter_manifest().document)
    invalid["template"]["sections"][0]["items"][0]["weight"] = "0"
    before = await session.scalar(
        select(func.count())
        .select_from(AssessmentTemplate)
        .where(AssessmentTemplate.code == "waiter-kln")
    )

    savepoint = await session.begin_nested()
    with pytest.raises(AssessmentTemplateImportError, match="positive"):
        ReviewedManifest.parse(json.dumps(invalid, ensure_ascii=False).encode())
    await savepoint.rollback()

    after = await session.scalar(
        select(func.count())
        .select_from(AssessmentTemplate)
        .where(AssessmentTemplate.code == "waiter-kln")
    )
    assert after == before
    assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_ten_worker_library_import_has_one_create_and_nine_no_ops():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    document = deepcopy(waiter_manifest().document)
    suffix = uuid4().hex[:12]
    template_code = f"waiter-kln-concurrency-{suffix}"
    methodology_code = f"waiter-kln-methodology-{suffix}"
    document["template"]["code"] = template_code
    document["template"]["methodology"]["code"] = methodology_code
    manifest = ReviewedManifest.parse(json.dumps(document, ensure_ascii=False).encode())

    async def worker():
        async with sessions() as value:
            result = await AssessmentLibraryImportService(value).apply(manifest, NOW)
            await value.commit()
            assert await value.scalar(select(1)) == 1
            return result

    try:
        results = await asyncio.gather(*(worker() for _ in range(10)))
        assert [value.action for value in results].count("create") == 1
        assert [value.action for value in results].count("no_op") == 9
        assert len({value.template_id for value in results}) == 1
        assert len({value.template_version_id for value in results}) == 1
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(
                delete(AssessmentTemplate).where(
                    AssessmentTemplate.code == template_code,
                    AssessmentTemplate.scope == "library",
                )
            )
            await cleanup.flush()
            await cleanup.execute(
                delete(AssessmentMethodology).where(
                    AssessmentMethodology.code == methodology_code,
                    AssessmentMethodology.owner_type == "system",
                )
            )
            await cleanup.commit()
        await engine.dispose()
