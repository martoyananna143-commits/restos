"""PostgreSQL integration tests for the assessment template lifecycle."""

from datetime import datetime, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
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
from app.internal.services.assessment_catalog_service import (
    AssessmentCatalogService,
)
from app.internal.services.assessment_template_service import (
    AdoptLibraryTemplate,
    AssessmentMethodologyNotFound,
    AssessmentTemplateCodeConflict,
    AssessmentTemplateDraftExists,
    AssessmentTemplateNotEditable,
    AssessmentTemplatePublicationInvalid,
    AssessmentTemplateService,
    AssessmentTemplateSourceInvalid,
    CreateNextDraft,
    InvalidAssessmentTemplateRequest,
    PublishMethodology,
    PublishTemplateVersion,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    owner = Account(
        id=uuid4(),
        display_name="Owner",
        status="active",
        security_version=1,
    )
    session.add(owner)
    await session.flush()
    company = Company(
        id=uuid4(),
        owner_account_id=owner.id,
        name="Company",
        code=f"company-{uuid4().hex[:8]}",
        timezone="UTC",
        locale="ru-RU",
        status="active",
    )
    session.add(company)
    await session.flush()
    ctx = SimpleNamespace(
        engine=engine,
        connection=connection,
        transaction=transaction,
        session=session,
        company=company,
        service=AssessmentTemplateService(session),
    )
    try:
        yield ctx
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def methodology(status="published", owner_type="system", **changes):
    values = dict(
        id=uuid4(),
        owner_type=owner_type,
        company_id=None,
        code=f"method-{uuid4().hex[:8]}",
        title="Service methodology",
        body="Stable domain guidance.",
        version=1,
        status=status,
        published_at=NOW if status != "draft" else None,
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    values.update(changes)
    return AssessmentMethodology(**values)


def template(**changes):
    values = dict(
        id=uuid4(),
        scope="library",
        company_id=None,
        source_library_version_id=None,
        code=f"template-{uuid4().hex[:8]}",
        name="Service audit",
        activity_type="measurement",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    values.update(changes)
    return AssessmentTemplate(**values)


def version(template_id, methodology_id, status="published", number=1, **changes):
    values = dict(
        id=uuid4(),
        template_id=template_id,
        version=number,
        status=status,
        methodology_id=methodology_id,
        local_description="Default local description",
        change_note=None,
        published_at=NOW if status == "published" else None,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return AssessmentTemplateVersion(**values)


async def seed_tree(session, *, method_status="published", version_status="published"):
    method = methodology(status=method_status)
    library = template()
    session.add_all([method, library])
    await session.flush()
    source = version(
        library.id, method.id, status=version_status, number=1
    )
    session.add(source)
    await session.flush()
    zone = AssessmentTemplateSection(
        id=uuid4(),
        template_version_id=source.id,
        parent_section_id=None,
        code="guest-zone",
        title="Guest zone",
        description="Zone description",
        section_kind="zone",
        sort_order=0,
        weight=Decimal("2.5"),
        created_at=NOW,
        updated_at=NOW,
    )
    group = AssessmentTemplateSection(
        id=uuid4(),
        template_version_id=source.id,
        parent_section_id=zone.id,
        code="service-group",
        title="Service",
        description=None,
        section_kind="group",
        sort_order=1,
        weight=Decimal("1"),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add_all([zone, group])
    await session.flush()
    choice = AssessmentTemplateItem(
        id=uuid4(),
        template_version_id=source.id,
        section_id=group.id,
        code="greeting-quality",
        prompt="How was the greeting?",
        guidance="Observe the first contact.",
        response_type="single_choice",
        is_required=True,
        sort_order=2,
        weight=Decimal("3"),
        min_value=Decimal("0"),
        max_value=Decimal("10"),
        passing_value=Decimal("6"),
        evidence_mode="optional_photo",
        criticality="critical",
        config={"scoring": {"mode": "weighted"}, "tags": ["service"]},
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(choice)
    await session.flush()
    options = [
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=choice.id,
            code=code,
            label=label,
            sort_order=index,
            numeric_value=value,
            is_disqualifying=index == 0,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, (code, label, value) in enumerate(
            [
                ("poor", "Poor", Decimal("0")),
                ("excellent", "Excellent", Decimal("10")),
            ]
        )
    ]
    session.add_all(options)
    await session.flush()
    return SimpleNamespace(
        methodology=method,
        library=library,
        source=source,
        zone=zone,
        group=group,
        item=choice,
        options=options,
    )


@pytest.mark.asyncio
async def test_publish_methodology(context):
    value = methodology(status="draft", code="service-standard", title=" Title ")
    context.session.add(value)
    await context.session.flush()
    result = await context.service.publish_methodology(
        PublishMethodology(value.id, NOW)
    )
    assert result.status == "published"
    assert result.published_at == NOW
    assert value.code == "service-standard"
    assert value.title == "Title"


@pytest.mark.asyncio
async def test_company_catalog_lists_blocked_draft_methodology(context):
    method = methodology(
        status="draft",
        owner_type="company",
        company_id=context.company.id,
    )
    company_template = template(
        scope="company",
        company_id=context.company.id,
        code=f"blocked-{uuid4().hex[:8]}",
    )
    context.session.add_all([method, company_template])
    await context.session.flush()
    draft = version(company_template.id, method.id, status="draft")
    context.session.add(draft)
    await context.session.flush()

    rows = await AssessmentCatalogService(
        context.session
    ).list_company_templates(context.company.id)

    assert len(rows) == 1
    assert rows[0]["template_id"] == company_template.id
    assert rows[0]["latest_draft"]["version_id"] == draft.id
    assert rows[0]["latest_published"] is None
    assert rows[0]["methodology"]["id"] == method.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["published", "retired"])
async def test_methodology_cannot_be_republished(context, status):
    value = methodology(status=status)
    context.session.add(value)
    await context.session.flush()
    with pytest.raises(AssessmentTemplatePublicationInvalid):
        await context.service.publish_methodology(
            PublishMethodology(value.id, NOW)
        )


@pytest.mark.asyncio
async def test_deleted_or_missing_methodology_is_unavailable(context):
    value = methodology(status="draft", deleted_at=NOW)
    context.session.add(value)
    await context.session.flush()
    for identifier in (value.id, uuid4()):
        with pytest.raises(AssessmentMethodologyNotFound):
            await context.service.publish_methodology(
                PublishMethodology(identifier, NOW)
            )


@pytest.mark.asyncio
async def test_publish_library_draft_with_valid_structure(context):
    seeded = await seed_tree(context.session, version_status="draft")
    result = await context.service.publish_template_version(
        PublishTemplateVersion(seeded.library.id, seeded.source.id, NOW)
    )
    assert result.status == "published"
    assert seeded.source.published_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["sections", "items"])
async def test_publication_requires_sections_and_items(context, missing):
    method = methodology()
    library = template()
    draft = version(library.id, method.id, status="draft")
    context.session.add_all([method, library])
    await context.session.flush()
    context.session.add(draft)
    await context.session.flush()
    if missing == "sections":
        pass
    else:
        section = AssessmentTemplateSection(
            id=uuid4(),
            template_version_id=draft.id,
            parent_section_id=None,
            code="zone",
            title="Zone",
            section_kind="zone",
            sort_order=0,
            weight=None,
            created_at=NOW,
            updated_at=NOW,
        )
        context.session.add(section)
        await context.session.flush()
    with pytest.raises(AssessmentTemplatePublicationInvalid):
        await context.service.publish_template_version(
            PublishTemplateVersion(library.id, draft.id, NOW)
        )


@pytest.mark.asyncio
async def test_choice_requires_two_options(context):
    seeded = await seed_tree(context.session, version_status="draft")
    await context.session.delete(seeded.options[1])
    await context.session.flush()
    with pytest.raises(AssessmentTemplatePublicationInvalid):
        await context.service.publish_template_version(
            PublishTemplateVersion(
                seeded.library.id, seeded.source.id, NOW
            )
        )


@pytest.mark.asyncio
async def test_non_choice_rejects_options_and_scalar_config(context):
    seeded = await seed_tree(context.session, version_status="draft")
    seeded.item.response_type = "boolean"
    with pytest.raises(AssessmentTemplatePublicationInvalid):
        await context.service.publish_template_version(
            PublishTemplateVersion(
                seeded.library.id, seeded.source.id, NOW
            )
        )
    seeded.item.response_type = "single_choice"
    seeded.item.config = ["invalid"]
    with pytest.raises(AssessmentTemplatePublicationInvalid):
        await context.service.publish_template_version(
            PublishTemplateVersion(
                seeded.library.id, seeded.source.id, NOW
            )
        )


@pytest.mark.asyncio
async def test_adopt_clones_complete_tree_and_provenance(context):
    seeded = await seed_tree(context.session)
    result = await context.service.adopt_library_template(
        AdoptLibraryTemplate(
            company_id=context.company.id,
            source_library_version_id=seeded.source.id,
            company_template_code="local-service",
            company_template_name=None,
            local_description=None,
            now=NOW,
        )
    )
    assert (result.section_count, result.item_count, result.option_count) == (2, 1, 2)
    adopted = await context.session.get(AssessmentTemplate, result.company_template_id)
    draft = await context.session.get(
        AssessmentTemplateVersion, result.draft_version_id
    )
    assert adopted.name == seeded.library.name
    assert adopted.source_library_version_id == seeded.source.id
    assert draft.methodology_id == seeded.methodology.id
    assert draft.local_description == seeded.source.local_description
    cloned_sections = (
        await context.session.execute(
            select(AssessmentTemplateSection).where(
                AssessmentTemplateSection.template_version_id == draft.id
            )
        )
    ).scalars().all()
    cloned_items = (
        await context.session.execute(
            select(AssessmentTemplateItem).where(
                AssessmentTemplateItem.template_version_id == draft.id
            )
        )
    ).scalars().all()
    assert {row.id for row in cloned_sections}.isdisjoint(
        {seeded.zone.id, seeded.group.id}
    )
    assert cloned_items[0].id != seeded.item.id
    assert cloned_items[0].config == seeded.item.config
    cloned_items[0].config["scoring"]["mode"] = "local"
    assert seeded.item.config["scoring"]["mode"] == "weighted"


@pytest.mark.asyncio
async def test_adopt_custom_name_description_and_duplicate_code(context):
    seeded = await seed_tree(context.session)
    first = await context.service.adopt_library_template(
        AdoptLibraryTemplate(
            context.company.id,
            seeded.source.id,
            "custom-copy",
            NOW,
            "Custom name",
            "Custom description",
        )
    )
    draft = await context.session.get(
        AssessmentTemplateVersion, first.draft_version_id
    )
    adopted = await context.session.get(
        AssessmentTemplate, first.company_template_id
    )
    assert adopted.name == "Custom name"
    assert draft.local_description == "Custom description"
    with pytest.raises(AssessmentTemplateCodeConflict):
        await context.service.adopt_library_template(
            AdoptLibraryTemplate(
                context.company.id, seeded.source.id, "custom-copy", NOW
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"source_status": "draft"},
        {"template_scope": "company"},
        {"template_status": "archived"},
        {"method_status": "retired"},
        {"method_owner": "company"},
    ],
)
async def test_adopt_rejects_invalid_source(context, change):
    seeded = await seed_tree(context.session)
    if "source_status" in change:
        seeded.source.status = change["source_status"]
        seeded.source.published_at = None
    if "template_scope" in change:
        seeded.library.scope = change["template_scope"]
        seeded.library.company_id = context.company.id
    if "template_status" in change:
        seeded.library.status = change["template_status"]
    if "method_status" in change:
        seeded.methodology.status = change["method_status"]
    if "method_owner" in change:
        seeded.methodology.owner_type = change["method_owner"]
        seeded.methodology.company_id = context.company.id
    await context.session.flush()
    with pytest.raises(
        (AssessmentTemplateSourceInvalid, AssessmentTemplatePublicationInvalid)
    ):
        await context.service.adopt_library_template(
            AdoptLibraryTemplate(
                context.company.id,
                seeded.source.id,
                f"copy-{uuid4().hex[:8]}",
                NOW,
            )
        )


@pytest.mark.asyncio
async def test_create_next_draft_clones_latest_published(context):
    seeded = await seed_tree(context.session)
    result = await context.service.create_next_draft(
        CreateNextDraft(seeded.library.id, seeded.source.id, NOW, "Next")
    )
    assert result.version == 2
    assert (result.section_count, result.item_count, result.option_count) == (2, 1, 2)
    assert seeded.source.status == "published"
    assert seeded.source.published_at == NOW
    await context.service.assert_editable_draft(
        seeded.library.id, result.draft_version_id
    )
    with pytest.raises(AssessmentTemplateNotEditable):
        await context.service.assert_editable_draft(
            seeded.library.id, seeded.source.id
        )


@pytest.mark.asyncio
async def test_existing_draft_blocks_next_draft(context):
    seeded = await seed_tree(context.session)
    draft = version(
        seeded.library.id,
        seeded.methodology.id,
        status="draft",
        number=2,
    )
    context.session.add(draft)
    await context.session.flush()
    with pytest.raises(AssessmentTemplateDraftExists):
        await context.service.create_next_draft(
            CreateNextDraft(seeded.library.id, seeded.source.id, NOW)
        )


@pytest.mark.asyncio
async def test_non_latest_published_cannot_seed_next_draft(context):
    seeded = await seed_tree(context.session)
    second = version(
        seeded.library.id,
        seeded.methodology.id,
        status="published",
        number=2,
    )
    context.session.add(second)
    await context.session.flush()
    with pytest.raises(AssessmentTemplateSourceInvalid):
        await context.service.create_next_draft(
            CreateNextDraft(seeded.library.id, seeded.source.id, NOW)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_request",
    [
        PublishMethodology("not-a-uuid", NOW),
        PublishMethodology(uuid4(), datetime(2026, 1, 1)),
    ],
)
async def test_runtime_validation_precedes_sql(context, invalid_request):
    with pytest.raises(InvalidAssessmentTemplateRequest):
        await context.service.publish_methodology(invalid_request)
    assert (await context.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_caller_owns_commit(context):
    seeded = await seed_tree(context.session)
    await context.service.create_next_draft(
        CreateNextDraft(seeded.library.id, seeded.source.id, NOW)
    )
    assert context.transaction.is_active
    assert (
        await context.session.scalar(
            select(func.count())
            .select_from(AssessmentTemplateVersion)
            .where(AssessmentTemplateVersion.template_id == seeded.library.id)
        )
        == 2
    )
