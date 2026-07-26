"""PostgreSQL integration tests for the additive assessment-template schema."""

from datetime import datetime, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    owner = Account(
        id=uuid4(),
        display_name="Template owner",
        status="active",
        security_version=1,
    )
    session.add(owner)
    await session.flush()
    company1 = Company(
        id=uuid4(),
        owner_account_id=owner.id,
        name="Company One",
        code=f"company-{uuid4().hex[:8]}",
        timezone="UTC",
        locale="ru-RU",
        status="active",
    )
    company2 = Company(
        id=uuid4(),
        owner_account_id=owner.id,
        name="Company Two",
        code=f"company-{uuid4().hex[:8]}",
        timezone="UTC",
        locale="ru-RU",
        status="active",
    )
    session.add_all([company1, company2])
    await session.flush()
    ctx = SimpleNamespace(
        engine=engine,
        connection=connection,
        transaction=transaction,
        session=session,
        owner=owner,
        company1=company1,
        company2=company2,
    )
    try:
        yield ctx
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def rejected(session: AsyncSession, value) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(value)
            await session.flush()
    assert (await session.execute(select(1))).scalar_one() == 1


def methodology(**changes):
    values = dict(
        id=uuid4(),
        owner_type="system",
        company_id=None,
        code=f"service-{uuid4().hex[:8]}",
        title="RestOS service methodology",
        body="Immutable methodology and instructions.",
        version=1,
        status="published",
        published_at=NOW,
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
        code=f"service-{uuid4().hex[:8]}",
        name="Service audit",
        activity_type="measurement",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    values.update(changes)
    return AssessmentTemplate(**values)


def version(template_id, methodology_id, **changes):
    values = dict(
        id=uuid4(),
        template_id=template_id,
        version=1,
        status="published",
        methodology_id=methodology_id,
        local_description=None,
        change_note="Initial publication",
        published_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return AssessmentTemplateVersion(**values)


def section(template_version_id, **changes):
    values = dict(
        id=uuid4(),
        template_version_id=template_version_id,
        parent_section_id=None,
        code=f"hall-{uuid4().hex[:8]}",
        title="Hall",
        description=None,
        section_kind="zone",
        sort_order=0,
        weight=Decimal("1"),
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return AssessmentTemplateSection(**values)


def item(template_version_id, section_id, **changes):
    values = dict(
        id=uuid4(),
        template_version_id=template_version_id,
        section_id=section_id,
        code=f"greeting-{uuid4().hex[:8]}",
        prompt="Was the guest greeted?",
        guidance=None,
        response_type="boolean",
        is_required=True,
        sort_order=0,
        weight=Decimal("1"),
        min_value=None,
        max_value=None,
        passing_value=None,
        evidence_mode="optional_comment",
        criticality="normal",
        config={},
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return AssessmentTemplateItem(**values)


async def seed_library_company_copy(session: AsyncSession, company_id):
    method = methodology()
    library = template()
    session.add_all([method, library])
    await session.flush()
    library_v1 = version(library.id, method.id)
    session.add(library_v1)
    await session.flush()
    company_template = template(
        scope="company",
        company_id=company_id,
        source_library_version_id=library_v1.id,
        code=f"local-{uuid4().hex[:8]}",
        name="Local service audit",
    )
    session.add(company_template)
    await session.flush()
    company_v1 = version(
        company_template.id,
        method.id,
        status="draft",
        published_at=None,
        local_description="Company-specific sections and questions.",
    )
    session.add(company_v1)
    await session.flush()
    return SimpleNamespace(
        methodology=method,
        library=library,
        library_v1=library_v1,
        company_template=company_template,
        company_v1=company_v1,
    )


@pytest.mark.asyncio
async def test_library_company_copy_versions_tree_items_and_options(context):
    seeded = await seed_library_company_copy(context.session, context.company1.id)
    zone = section(seeded.company_v1.id, code="guest-zone", section_kind="zone")
    group = section(
        seeded.company_v1.id,
        parent_section_id=zone.id,
        code="greeting-group",
        section_kind="group",
        sort_order=1,
    )
    context.session.add_all([zone, group])
    await context.session.flush()
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
    items = [
        item(
            seeded.company_v1.id,
            group.id,
            code=f"question-{index}",
            response_type=response_type,
            sort_order=index,
        )
        for index, response_type in enumerate(response_types)
    ]
    context.session.add_all(items)
    await context.session.flush()
    options = [
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=items[5].id,
            code="yes",
            label="Yes",
            sort_order=0,
            numeric_value=Decimal("1"),
            is_disqualifying=False,
            created_at=NOW,
            updated_at=NOW,
        ),
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=items[5].id,
            code="no",
            label="No",
            sort_order=1,
            numeric_value=Decimal("0"),
            is_disqualifying=True,
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    context.session.add_all(options)
    await context.session.flush()
    second_version = version(
        seeded.company_template.id,
        seeded.methodology.id,
        version=2,
        status="draft",
        published_at=None,
    )
    context.session.add(second_version)
    await context.session.flush()
    same_section_code = section(second_version.id, code=zone.code)
    context.session.add(same_section_code)
    await context.session.flush()
    context.session.add(
        item(second_version.id, same_section_code.id, code=items[0].code)
    )
    await context.session.flush()
    assert seeded.library.scope == "library"
    assert seeded.company_template.source_library_version_id == seeded.library_v1.id
    assert seeded.company_v1.methodology_id == seeded.library_v1.methodology_id
    assert seeded.methodology.is_editable is False
    assert seeded.company_v1.is_editable is True


@pytest.mark.asyncio
async def test_company_codes_are_isolated_between_companies(context):
    common = f"daily-{uuid4().hex[:8]}"
    first = template(
        scope="company",
        company_id=context.company1.id,
        code=common,
    )
    second = template(
        scope="company",
        company_id=context.company2.id,
        code=common,
    )
    context.session.add_all([first, second])
    await context.session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"owner_type": "system", "company_id": uuid4()},
        {"owner_type": "company", "company_id": None},
        {"owner_type": "invalid"},
        {"code": "Not Safe"},
        {"version": 0},
        {"status": "invalid"},
        {"status": "published", "published_at": None},
        {"status": "draft", "published_at": NOW},
    ],
)
async def test_methodology_constraints_reject_invalid_state(context, changes):
    if changes.get("company_id") is not None:
        changes["company_id"] = context.company1.id
    await rejected(context.session, methodology(**changes))


@pytest.mark.asyncio
async def test_methodology_company_fk_and_active_uniqueness(context):
    await rejected(
        context.session,
        methodology(owner_type="company", company_id=uuid4()),
    )
    first = methodology(code="service-standard", version=1)
    context.session.add(first)
    await context.session.flush()
    await rejected(
        context.session,
        methodology(code="service-standard", version=1),
    )
    first.deleted_at = NOW
    await context.session.flush()
    context.session.add(methodology(code="service-standard", version=1))
    await context.session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "library", "company_id": uuid4()},
        {"scope": "company", "company_id": None},
        {"scope": "invalid"},
        {"code": "Invalid Code"},
        {"activity_type": "unknown"},
        {"status": "unknown"},
    ],
)
async def test_template_constraints_reject_invalid_state(context, changes):
    if changes.get("company_id") is not None:
        changes["company_id"] = context.company1.id
    await rejected(context.session, template(**changes))


@pytest.mark.asyncio
async def test_template_source_scope_fks_and_uniqueness(context):
    method = methodology()
    library = template(code="library-standard")
    context.session.add_all([method, library])
    await context.session.flush()
    library_v1 = version(library.id, method.id)
    context.session.add(library_v1)
    await context.session.flush()
    await rejected(
        context.session,
        template(
            scope="library",
            source_library_version_id=library_v1.id,
        ),
    )
    await rejected(
        context.session,
        template(scope="company", company_id=uuid4()),
    )
    await rejected(context.session, template(code="library-standard"))
    company_code = "company-standard"
    first = template(
        scope="company",
        company_id=context.company1.id,
        code=company_code,
    )
    context.session.add(first)
    await context.session.flush()
    await rejected(
        context.session,
        template(
            scope="company",
            company_id=context.company1.id,
            code=company_code,
        ),
    )
    await rejected(
        context.session,
        template(
            scope="company",
            company_id=context.company1.id,
            source_library_version_id=uuid4(),
        ),
    )


@pytest.mark.asyncio
async def test_version_constraints_and_foreign_keys(context):
    method = methodology()
    library = template()
    context.session.add_all([method, library])
    await context.session.flush()
    first = version(library.id, method.id)
    context.session.add(first)
    await context.session.flush()
    await rejected(context.session, version(library.id, method.id))
    await rejected(context.session, version(library.id, method.id, version=0))
    await rejected(
        context.session,
        version(library.id, method.id, status="published", published_at=None),
    )
    await rejected(
        context.session,
        version(library.id, method.id, status="draft", published_at=NOW),
    )
    await rejected(context.session, version(uuid4(), method.id))
    await rejected(context.session, version(library.id, uuid4(), version=2))


@pytest.mark.asyncio
async def test_section_tree_constraints(context):
    seeded = await seed_library_company_copy(context.session, context.company1.id)
    version2 = version(
        seeded.company_template.id,
        seeded.methodology.id,
        version=2,
        status="draft",
        published_at=None,
    )
    context.session.add(version2)
    await context.session.flush()
    parent = section(seeded.company_v1.id, code="parent")
    context.session.add(parent)
    await context.session.flush()
    await rejected(
        context.session,
        section(
            version2.id,
            parent_section_id=parent.id,
            code="wrong-parent",
        ),
    )
    self_id = uuid4()
    await rejected(
        context.session,
        section(
            seeded.company_v1.id,
            id=self_id,
            parent_section_id=self_id,
            code="self-parent",
        ),
    )
    await rejected(
        context.session,
        section(seeded.company_v1.id, code="negative-order", sort_order=-1),
    )
    await rejected(
        context.session,
        section(seeded.company_v1.id, code="negative-weight", weight=-1),
    )
    await rejected(
        context.session,
        section(seeded.company_v1.id, code=parent.code),
    )
    await rejected(context.session, section(uuid4(), code="missing-version"))


@pytest.mark.asyncio
async def test_item_constraints_and_cross_version_section(context):
    seeded = await seed_library_company_copy(context.session, context.company1.id)
    section1 = section(seeded.company_v1.id, code="first-section")
    context.session.add(section1)
    await context.session.flush()
    version2 = version(
        seeded.company_template.id,
        seeded.methodology.id,
        version=2,
        status="draft",
        published_at=None,
    )
    context.session.add(version2)
    await context.session.flush()
    await rejected(context.session, item(version2.id, section1.id))
    await rejected(
        context.session,
        item(seeded.company_v1.id, section1.id, code="bad-order", sort_order=-1),
    )
    await rejected(
        context.session,
        item(seeded.company_v1.id, section1.id, code="bad-weight", weight=-1),
    )
    await rejected(
        context.session,
        item(
            seeded.company_v1.id,
            section1.id,
            code="bad-range",
            min_value=10,
            max_value=1,
        ),
    )
    await rejected(
        context.session,
        item(
            seeded.company_v1.id,
            section1.id,
            code="bad-passing",
            min_value=1,
            max_value=5,
            passing_value=6,
        ),
    )
    await rejected(
        context.session,
        item(
            seeded.company_v1.id,
            section1.id,
            code="bad-response",
            response_type="unknown",
        ),
    )
    await rejected(
        context.session,
        item(
            seeded.company_v1.id,
            section1.id,
            code="bad-evidence",
            evidence_mode="unknown",
        ),
    )
    await rejected(
        context.session,
        item(
            seeded.company_v1.id,
            section1.id,
            code="bad-criticality",
            criticality="unknown",
        ),
    )
    first = item(seeded.company_v1.id, section1.id, code="duplicate-item")
    context.session.add(first)
    await context.session.flush()
    await rejected(
        context.session,
        item(seeded.company_v1.id, section1.id, code=first.code),
    )
    await rejected(
        context.session,
        item(seeded.company_v1.id, uuid4(), code="missing-section"),
    )


@pytest.mark.asyncio
async def test_option_constraints_and_foreign_key(context):
    seeded = await seed_library_company_copy(context.session, context.company1.id)
    section1 = section(seeded.company_v1.id, code="choice-section")
    context.session.add(section1)
    await context.session.flush()
    choice = item(
        seeded.company_v1.id,
        section1.id,
        code="choice-item",
        response_type="single_choice",
    )
    context.session.add(choice)
    await context.session.flush()
    option = AssessmentTemplateItemOption(
        id=uuid4(),
        item_id=choice.id,
        code="first",
        label="First",
        sort_order=0,
        numeric_value=1,
        is_disqualifying=False,
        created_at=NOW,
        updated_at=NOW,
    )
    context.session.add(option)
    await context.session.flush()
    await rejected(
        context.session,
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=choice.id,
            code=option.code,
            label="Duplicate",
            sort_order=1,
            numeric_value=None,
            is_disqualifying=False,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
    await rejected(
        context.session,
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=choice.id,
            code="negative",
            label="Negative",
            sort_order=-1,
            numeric_value=None,
            is_disqualifying=False,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
    await rejected(
        context.session,
        AssessmentTemplateItemOption(
            id=uuid4(),
            item_id=uuid4(),
            code="missing-item",
            label="Missing",
            sort_order=0,
            numeric_value=None,
            is_disqualifying=False,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
