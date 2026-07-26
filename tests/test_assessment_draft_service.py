"""PostgreSQL integration tests for atomic draft document editing."""

from datetime import datetime, timezone
from dataclasses import fields
from decimal import Decimal
import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account import Account
from app.infra.database.models.assessment_template import (
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
)
from app.infra.database.models.company import Company
from app.internal.services.assessment_draft_service import (
    AssessmentDraftNotEditable,
    AssessmentDraftRevisionConflict,
    AssessmentDraftService,
    AssessmentDraftStructureInvalid,
    DraftItemInput,
    DraftOptionInput,
    DraftSectionInput,
    GetDraftDocument,
    SaveDraftDocument,
)


NOW = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "field_name",
    [
        "methodology_id",
        "source_library_version_id",
        "company_id",
        "scope",
        "activity_type",
        "version",
        "status",
        "published_at",
        "edit_revision",
    ],
)
def test_save_draft_document_rejects_forbidden_write_fields(field_name):
    allowed_fields = {field.name for field in fields(SaveDraftDocument)}
    assert "expected_edit_revision" in allowed_fields
    assert field_name not in allowed_fields
    with pytest.raises(TypeError):
        SaveDraftDocument(
            template_id=uuid4(),
            template_version_id=uuid4(),
            expected_edit_revision=1,
            sections=[],
            now=NOW,
            **{field_name: None},
        )


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    account = Account(
        id=uuid4(), display_name="Owner", status="active", security_version=1
    )
    session.add(account)
    await session.flush()
    company = Company(
        id=uuid4(), owner_account_id=account.id, name="Company",
        code=f"company-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    method = AssessmentMethodology(
        id=uuid4(), owner_type="system", company_id=None, code="service",
        title="Method", body="Immutable body", version=1, status="published",
        published_at=NOW, created_at=NOW, updated_at=NOW,
    )
    template = AssessmentTemplate(
        id=uuid4(), scope="company", company_id=company.id,
        source_library_version_id=None, code="local-service", name="Draft",
        activity_type="measurement", status="active",
        created_at=NOW, updated_at=NOW,
    )
    session.add_all([company, method])
    await session.flush()
    session.add(template)
    await session.flush()
    version = AssessmentTemplateVersion(
        id=uuid4(), template_id=template.id, version=1, edit_revision=1,
        status="draft", methodology_id=method.id, published_at=None,
        created_at=NOW, updated_at=NOW,
    )
    session.add(version)
    await session.flush()
    try:
        yield session, template, version, method
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def document(template, version, revision=1, *, name="Renamed"):
    return SaveDraftDocument(
        template_id=template.id,
        template_version_id=version.id,
        expected_edit_revision=revision,
        template_name=name,
        local_description=" Local ",
        change_note=" Edit ",
        now=NOW,
        sections=[
            DraftSectionInput(
                code=" Guest-Zone ", title=" Guest zone ", description=None,
                section_kind="zone", sort_order=0, weight=Decimal("1"),
                parent_code=None,
                items=[
                    DraftItemInput(
                        code=" Quality ", prompt=" Quality? ", guidance=None,
                        response_type="single_choice", is_required=True,
                        sort_order=0, weight=Decimal("2"), min_value=Decimal("0"),
                        max_value=Decimal("10"), passing_value=Decimal("6"),
                        evidence_mode="optional_photo", criticality="critical",
                        config={"nested": {"value": 1}},
                        options=[
                            DraftOptionInput("bad", " Bad ", 0, Decimal("0"), True),
                            DraftOptionInput("good", " Good ", 1, Decimal("10"), False),
                        ],
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_save_and_read_document(context):
    session, template, version, method = context
    service = AssessmentDraftService(session)
    result = await service.save_draft_document(document(template, version))
    assert result.previous_edit_revision == 1
    assert result.edit_revision == 2
    assert (result.section_count, result.item_count, result.option_count) == (1, 1, 2)
    loaded = await service.get_draft_document(GetDraftDocument(template.id, version.id))
    assert loaded.template["name"] == "Renamed"
    assert loaded.version["edit_revision"] == 2
    assert loaded.methodology["body"] == method.body
    assert loaded.sections[0]["code"] == "guest-zone"
    assert loaded.sections[0]["items"][0]["options"][0]["label"] == "Bad"


@pytest.mark.asyncio
async def test_empty_document_and_revision_progress(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    empty = SaveDraftDocument(template.id, version.id, 1, [], NOW)
    assert (await service.save_draft_document(empty)).edit_revision == 2
    second = SaveDraftDocument(template.id, version.id, 2, [], NOW)
    assert (await service.save_draft_document(second)).edit_revision == 3


@pytest.mark.asyncio
async def test_stale_revision_is_atomic(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    await service.save_draft_document(document(template, version))
    with pytest.raises(AssessmentDraftRevisionConflict):
        await service.save_draft_document(document(template, version, 1, name="Lost"))
    assert template.name == "Renamed"
    assert version.edit_revision == 2
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_full_replacement_removes_old_rows(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    await service.save_draft_document(document(template, version))
    await service.save_draft_document(
        SaveDraftDocument(template.id, version.id, 2, [], NOW)
    )
    assert (await service.get_draft_document(
        GetDraftDocument(template.id, version.id)
    )).sections == []


@pytest.mark.asyncio
async def test_duplicate_codes_and_missing_parent_rejected(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    section = document(template, version).sections[0]
    with pytest.raises(AssessmentDraftStructureInvalid):
        await service.save_draft_document(
            SaveDraftDocument(template.id, version.id, 1, [section, section], NOW)
        )
    missing = DraftSectionInput(
        "child", "", None, "group", 0, None, "missing", []
    )
    with pytest.raises(AssessmentDraftStructureInvalid):
        await service.save_draft_document(
            SaveDraftDocument(template.id, version.id, 1, [missing], NOW)
        )


@pytest.mark.asyncio
async def test_published_version_is_not_editable(context):
    session, template, version, _ = context
    version.status = "published"
    version.published_at = NOW
    await session.flush()
    with pytest.raises(AssessmentDraftNotEditable):
        await AssessmentDraftService(session).get_draft_document(
            GetDraftDocument(template.id, version.id)
        )


@pytest.mark.asyncio
async def test_large_restaurant_document_round_trip(context):
    session, template, version, method = context
    service = AssessmentDraftService(session)
    evidence_modes = [
        "none",
        "optional_photo",
        "required_photo",
        "optional_comment",
        "required_comment",
        "photo_and_comment",
    ]
    criticalities = ["normal", "critical", "stop_factor"]
    response_types = [
        "boolean",
        "score",
        "integer",
        "decimal",
        "text",
        "single_choice",
        "multi_choice",
        "date",
        "time",
    ]
    sections = []
    expected_options = 0
    for section_index in range(10):
        items = []
        for item_index in range(24):
            absolute = section_index * 24 + item_index
            response_type = response_types[absolute % len(response_types)]
            options = []
            if response_type in {"single_choice", "multi_choice"}:
                options = [
                    DraftOptionInput(
                        code=f"option-{option_index}",
                        label=f"Option {option_index}",
                        sort_order=option_index,
                        numeric_value=Decimal(option_index),
                        is_disqualifying=option_index == 0,
                    )
                    for option_index in range(2)
                ]
                expected_options += 2
            numeric = response_type in {"score", "integer", "decimal"}
            items.append(
                DraftItemInput(
                    code=f"item-{absolute:03d}",
                    prompt=f"Restaurant control point {absolute}",
                    guidance=f"Guidance {absolute}",
                    response_type=response_type,
                    is_required=absolute % 2 == 0,
                    sort_order=item_index % 5,
                    weight=Decimal((absolute % 7) + 1) / Decimal("10"),
                    min_value=Decimal("0") if numeric else None,
                    max_value=Decimal("10") if numeric else None,
                    passing_value=Decimal("6") if numeric else None,
                    evidence_mode=evidence_modes[absolute % len(evidence_modes)],
                    criticality=criticalities[absolute % len(criticalities)],
                    config={
                        "index": absolute,
                        "flags": [True, False, None],
                        "nested": {"section": section_index},
                    },
                    options=options,
                )
            )
        sections.append(
            DraftSectionInput(
                code=f"zone-{section_index:02d}",
                title=f"Zone {section_index}",
                description=f"Description {section_index}",
                section_kind="zone" if section_index % 2 == 0 else "group",
                sort_order=section_index % 3,
                weight=Decimal(section_index + 1),
                parent_code=(
                    None if section_index == 0 else f"zone-{section_index - 1:02d}"
                ),
                items=items,
            )
        )
    request_value = SaveDraftDocument(
        template_id=template.id,
        template_version_id=version.id,
        expected_edit_revision=1,
        sections=sections,
        now=NOW,
        template_name="Large restaurant audit",
        local_description="Full operational form",
    )
    result = await service.save_draft_document(request_value)
    assert result.section_count == 10
    assert result.item_count == 240
    assert result.option_count == expected_options
    assert result.edit_revision == 2
    first = await service.get_draft_document(
        GetDraftDocument(template.id, version.id)
    )
    second = await service.get_draft_document(
        GetDraftDocument(template.id, version.id)
    )
    assert first == second
    assert sum(len(section["items"]) for section in first.sections) == 240
    assert sum(
        len(item["options"])
        for section in first.sections
        for item in section["items"]
    ) == expected_options
    by_code = {section["code"]: section for section in first.sections}
    assert by_code["zone-09"]["parent_code"] == "zone-08"
    assert [section["code"] for section in first.sections] == sorted(
        [section["code"] for section in first.sections],
        key=lambda code: (int(code[-2:]) % 3, code),
    )
    assert method.body == "Immutable body"
    assert template.source_library_version_id is None


@pytest.mark.asyncio
async def test_all_response_types_json_independence_and_tie_order(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    response_types = [
        "boolean", "score", "integer", "decimal", "text",
        "single_choice", "multi_choice", "date", "time",
    ]
    source_config = {
        "nested": {"array": [1, "two", True, None]},
        "enabled": False,
    }
    items = []
    for index, response_type in enumerate(reversed(response_types)):
        options = []
        if response_type == "single_choice":
            options = [
                DraftOptionInput("only", "Only", 0, Decimal("1"), True)
            ]
        elif response_type == "multi_choice":
            options = [
                DraftOptionInput("z-option", "Z", 0, None, False),
                DraftOptionInput("a-option", "A", 0, Decimal("2"), True),
            ]
        items.append(
            DraftItemInput(
                code=f"{response_type.replace('_', '-')}-item",
                prompt=response_type,
                guidance=None,
                response_type=response_type, is_required=False, sort_order=0,
                weight=None, min_value=None, max_value=None, passing_value=None,
                evidence_mode="none", criticality="normal",
                config=source_config, options=options,
            )
        )
    sections = [
        DraftSectionInput(
            "z-zone", "Z", None, "zone", 0, None, None, items
        ),
        DraftSectionInput(
            "a-zone", "A", None, "zone", 0, None, None, []
        ),
    ]
    await service.save_draft_document(
        SaveDraftDocument(template.id, version.id, 1, sections, NOW)
    )
    source_config["nested"]["array"][0] = 999
    first = await service.get_draft_document(
        GetDraftDocument(template.id, version.id)
    )
    assert [value["code"] for value in first.sections] == ["a-zone", "z-zone"]
    assert [item["code"] for item in first.sections[1]["items"]] == sorted(
        item["code"] for item in first.sections[1]["items"]
    )
    multi = next(
        item for item in first.sections[1]["items"]
        if item["response_type"] == "multi_choice"
    )
    assert [option["code"] for option in multi["options"]] == [
        "a-option", "z-option"
    ]
    assert multi["options"][0]["numeric_value"] == Decimal("2")
    assert multi["options"][0]["is_disqualifying"] is True
    assert multi["config"]["nested"]["array"][0] == 1
    multi["config"]["nested"]["array"][0] = 777
    reread = await service.get_draft_document(
        GetDraftDocument(template.id, version.id)
    )
    persisted = next(
        item for item in reread.sections[1]["items"]
        if item["response_type"] == "multi_choice"
    )
    assert persisted["config"]["nested"]["array"][0] == 1


@pytest.mark.asyncio
async def test_non_choice_options_are_rejected_without_mutation(context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    invalid_item = DraftItemInput(
        "bad", "Bad", None, "boolean", False, 0, None, None, None, None,
        "none", "normal", {}, [DraftOptionInput("yes", "Yes", 0, None, False)],
    )
    section = DraftSectionInput(
        "zone", "Zone", None, "zone", 0, None, None, [invalid_item]
    )
    with pytest.raises(AssessmentDraftStructureInvalid):
        await service.save_draft_document(
            SaveDraftDocument(template.id, version.id, 1, [section], NOW)
        )
    assert version.edit_revision == 1
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_late_failure_rolls_back_complete_document(monkeypatch, context):
    session, template, version, _ = context
    service = AssessmentDraftService(session)
    await service.save_draft_document(document(template, version))
    old = await service.get_draft_document(GetDraftDocument(template.id, version.id))
    old_name = template.name
    old_description = version.local_description
    old_note = version.change_note
    template_id = template.id
    template_version_id = version.id
    original_flush = session.flush
    calls = 0

    async def late_failure(*args, **kwargs):
        nonlocal calls
        calls += 1
        await original_flush(*args, **kwargs)
        if calls == 3:
            raise RuntimeError("late test failure")

    monkeypatch.setattr(session, "flush", late_failure)
    with pytest.raises(RuntimeError, match="late test failure"):
        await service.save_draft_document(
            document(template, version, revision=2, name="Must roll back")
        )
    monkeypatch.setattr(session, "flush", original_flush)
    session.expire_all()
    restored = await service.get_draft_document(
        GetDraftDocument(template_id, template_version_id)
    )
    restored_template = await session.get(AssessmentTemplate, template_id)
    restored_version = await session.get(
        AssessmentTemplateVersion, template_version_id
    )
    assert restored.sections == old.sections
    assert restored_template.name == old_name
    assert restored_version.local_description == old_description
    assert restored_version.change_note == old_note
    assert restored_version.edit_revision == 2
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_full_replacement_has_fresh_ids_and_no_orphans(context):
    session, template, version, method = context
    service = AssessmentDraftService(session)
    await service.save_draft_document(document(template, version))
    old_sections = set(
        (await session.execute(select(AssessmentTemplateSection.id))).scalars()
    )
    old_items = set(
        (await session.execute(select(AssessmentTemplateItem.id))).scalars()
    )
    old_options = set(
        (await session.execute(select(AssessmentTemplateItemOption.id))).scalars()
    )
    replacement = DraftSectionInput(
        "new-zone", "New", None, "zone", 7, Decimal("4"), None,
        [
            DraftItemInput(
                "new-item", "New item", None, "single_choice", True, 5,
                Decimal("3"), None, None, None, "required_comment",
                "stop_factor", {}, [
                    DraftOptionInput("new-option", "New", 0, None, False)
                ],
            )
        ],
    )
    result = await service.save_draft_document(
        SaveDraftDocument(
            template.id, version.id, 2, [replacement], NOW,
            "Replacement", "Replacement description", "Replacement note",
        )
    )
    new_sections = set(
        (await session.execute(select(AssessmentTemplateSection.id))).scalars()
    )
    new_items = set(
        (await session.execute(select(AssessmentTemplateItem.id))).scalars()
    )
    new_options = set(
        (await session.execute(select(AssessmentTemplateItemOption.id))).scalars()
    )
    assert old_sections.isdisjoint(new_sections)
    assert old_items.isdisjoint(new_items)
    assert old_options.isdisjoint(new_options)
    assert result.edit_revision == 3
    assert version.methodology_id == method.id
    assert template.source_library_version_id is None
    assert template.name == "Replacement"


@pytest.mark.asyncio
async def test_optimistic_concurrency_has_one_complete_winner():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        account = Account(
            id=uuid4(),
            display_name="Concurrency owner",
            status="active",
            security_version=1,
        )
        company = Company(
            id=uuid4(),
            owner_account_id=account.id,
            name="Concurrency company",
            code=f"concurrency-{uuid4().hex[:8]}",
            timezone="UTC",
            locale="ru-RU",
            status="active",
        )
        method = AssessmentMethodology(
            id=uuid4(),
            owner_type="system",
            company_id=None,
            code=f"concurrency-{uuid4().hex[:8]}",
            title="Concurrency method",
            body="Immutable body",
            version=1,
            status="published",
            published_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        template = AssessmentTemplate(
            id=uuid4(),
            scope="company",
            company_id=company.id,
            source_library_version_id=None,
            code=f"concurrency-{uuid4().hex[:8]}",
            name="Concurrency draft",
            activity_type="measurement",
            status="active",
            created_at=NOW,
            updated_at=NOW,
        )
        version = AssessmentTemplateVersion(
            id=uuid4(),
            template_id=template.id,
            version=1,
            edit_revision=1,
            status="draft",
            methodology_id=method.id,
            published_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        setup.add(account)
        await setup.flush()
        setup.add(company)
        await setup.flush()
        setup.add(method)
        await setup.flush()
        setup.add(template)
        await setup.flush()
        setup.add(version)
        await setup.flush()
        template_id = template.id
        template_version_id = version.id
        expected_edit_revision = version.edit_revision
        methodology_id = method.id
        source_library_version_id = template.source_library_version_id
        await setup.commit()

    async with AsyncSession(engine, expire_on_commit=False) as visible:
        assert await visible.get(AssessmentTemplate, template_id) is not None
        assert (
            await visible.get(AssessmentTemplateVersion, template_version_id)
            is not None
        )

    left_section = DraftSectionInput(
        "left-zone", "Left", None, "zone", 0, None, None, []
    )
    right_section = DraftSectionInput(
        "right-zone", "Right", None, "zone", 0, None, None, []
    )

    async def attempt(section):
        async with AsyncSession(engine, expire_on_commit=False) as contender:
            try:
                result = await AssessmentDraftService(contender).save_draft_document(
                    SaveDraftDocument(
                        template_id,
                        template_version_id,
                        expected_edit_revision,
                        [section],
                        NOW,
                    )
                )
                await contender.commit()
                return result
            except AssessmentDraftRevisionConflict as error:
                await contender.rollback()
                return error

    outcomes = await asyncio.gather(attempt(left_section), attempt(right_section))
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    assert sum(
        isinstance(value, AssessmentDraftRevisionConflict) for value in outcomes
    ) == 1
    async with AsyncSession(engine, expire_on_commit=False) as check:
        final = await AssessmentDraftService(check).get_draft_document(
            GetDraftDocument(template_id, template_version_id)
        )
        assert final.version["edit_revision"] == 2
        assert len(final.sections) == 1
        assert (
            final.sections[0]["code"],
            final.sections[0]["title"],
            final.sections[0]["items"],
        ) in [
            ("left-zone", "Left", []),
            ("right-zone", "Right", []),
        ]
        persisted_version = await check.get(
            AssessmentTemplateVersion, template_version_id
        )
        persisted_template = await check.get(AssessmentTemplate, template_id)
        assert persisted_version.methodology_id == methodology_id
        assert (
            persisted_template.source_library_version_id
            == source_library_version_id
        )
    await engine.dispose()
