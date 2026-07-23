"""PostgreSQL integration tests for secure workforce invitations."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import (
    Invitation,
    InvitationScopeVenue,
    InvitationVenue,
)
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.workforce_invitation_service import (
    CreateWorkforceInvitation,
    InvitationCodeCollisionExhausted,
    InvalidWorkforceInvitation,
    PendingWorkforceInvitationExists,
    WorkforceInvitationForbidden,
    WorkforceInvitationService,
    _postgres_constraint_name,
)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
PEPPER = b"p" * 32


class Codes:
    def __init__(self, *codes):
        self._codes = iter(codes)

    def __call__(self):
        return next(self._codes)


@pytest_asyncio.fixture
async def invitation_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    owner, company_manager, venue_manager, outsider, other_owner = [
        Account(id=uuid4(), display_name=name, status="active")
        for name in ("Owner", "Company manager", "Venue manager", "Outsider", "Other")
    ]
    session.add_all([owner, company_manager, venue_manager, outsider, other_owner])
    await session.flush()
    company = Company(
        id=uuid4(), owner_account_id=owner.id, name="Company",
        code=f"company-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    other_company = Company(
        id=uuid4(), owner_account_id=other_owner.id, name="Other",
        code=f"other-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    session.add_all([company, other_company])
    await session.flush()
    company_access = AccessProfile(
        id=uuid4(), company_id=company.id, name="Company invite",
        code=f"company-invite-{uuid4().hex[:8]}", maximum_scope="company",
        is_system=False, is_active=True, version=1,
    )
    venue_access = AccessProfile(
        id=uuid4(), company_id=company.id, name="Venue invite",
        code=f"venue-invite-{uuid4().hex[:8]}", maximum_scope="working_venues",
        is_system=False, is_active=True, version=1,
    )
    limited_access = AccessProfile(
        id=uuid4(), company_id=company.id, name="Limited",
        code=f"limited-{uuid4().hex[:8]}", maximum_scope="self",
        is_system=False, is_active=True, version=1,
    )
    other_access = AccessProfile(
        id=uuid4(), company_id=other_company.id, name="Other",
        code=f"other-access-{uuid4().hex[:8]}", maximum_scope="company",
        is_system=False, is_active=True, version=1,
    )
    session.add_all([company_access, venue_access, limited_access, other_access])
    await session.flush()
    session.add_all([
        AccessProfilePermission(
            access_profile_id=company_access.id, permission_code="employee.invite"
        ),
        AccessProfilePermission(
            access_profile_id=venue_access.id, permission_code="employee.invite"
        ),
    ])
    position = Position(
        id=uuid4(), company_id=company.id, name="Worker",
        code=f"worker-{uuid4().hex[:8]}", is_active=True, sort_order=0,
    )
    other_position = Position(
        id=uuid4(), company_id=other_company.id, name="Other worker",
        code=f"other-worker-{uuid4().hex[:8]}", is_active=True, sort_order=0,
    )
    session.add_all([position, other_position])
    await session.flush()
    venue1 = Venue(
        id=uuid4(), company_id=company.id, name="Venue 1",
        code=f"venue-one-{uuid4().hex[:8]}", status="active",
    )
    venue2 = Venue(
        id=uuid4(), company_id=company.id, name="Venue 2",
        code=f"venue-two-{uuid4().hex[:8]}", status="active",
    )
    closed = Venue(
        id=uuid4(), company_id=company.id, name="Closed",
        code=f"closed-{uuid4().hex[:8]}", status="closed",
    )
    deleted = Venue(
        id=uuid4(), company_id=company.id, name="Deleted",
        code=f"deleted-{uuid4().hex[:8]}", status="active", deleted_at=NOW,
    )
    other_venue = Venue(
        id=uuid4(), company_id=other_company.id, name="Other",
        code=f"other-venue-{uuid4().hex[:8]}", status="active",
    )
    session.add_all([venue1, venue2, closed, deleted, other_venue])
    await session.flush()
    company_profile = EmployeeProfile(
        id=uuid4(), company_id=company.id, account_id=company_manager.id,
        full_name="Company manager", employment_status="active",
    )
    venue_profile = EmployeeProfile(
        id=uuid4(), company_id=company.id, account_id=venue_manager.id,
        full_name="Venue manager", employment_status="active",
    )
    targets = [
        EmployeeProfile(
            id=uuid4(), company_id=company.id, full_name=f"Invitee {index}",
            employment_status="invited",
        )
        for index in range(30)
    ]
    other_target = EmployeeProfile(
        id=uuid4(), company_id=other_company.id, full_name="Other invitee",
        employment_status="invited",
    )
    session.add_all([company_profile, venue_profile, other_target, *targets])
    await session.flush()
    company_assignment = EmployeeAssignment(
        id=uuid4(), company_id=company.id, employee_profile_id=company_profile.id,
        position_id=position.id, access_profile_id=company_access.id,
        scope_type="company", is_primary=False, status="active",
        starts_at=NOW - timedelta(days=1),
    )
    venue_assignment = EmployeeAssignment(
        id=uuid4(), company_id=company.id, employee_profile_id=venue_profile.id,
        position_id=position.id, access_profile_id=venue_access.id,
        scope_type="working_venues", is_primary=False, status="active",
        starts_at=NOW - timedelta(days=1),
    )
    session.add_all([company_assignment, venue_assignment])
    await session.flush()
    session.add(AssignmentVenue(
        assignment_id=venue_assignment.id, venue_id=venue1.id,
        company_id=company.id,
    ))
    await session.flush()
    ctx = SimpleNamespace(
        session=session, owner=owner, company_manager=company_manager,
        venue_manager=venue_manager, outsider=outsider, company=company,
        other_company=other_company, position=position,
        other_position=other_position, company_access=company_access,
        venue_access=venue_access, limited_access=limited_access,
        other_access=other_access, venue1=venue1, venue2=venue2,
        closed=closed, deleted=deleted, other_venue=other_venue,
        targets=targets, other_target=other_target,
    )
    try:
        yield ctx
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def request(ctx, target, actor=None, scope="company", working=(), scoped=(),
            expires_at=None, ttl=timedelta(hours=1), now=NOW, access=None,
            position=None, company=None):
    return CreateWorkforceInvitation(
        actor_account_id=(actor or ctx.owner).id,
        company_id=company or ctx.company.id,
        employee_profile_id=target.id,
        position_id=(position or ctx.position).id,
        access_profile_id=(access or ctx.company_access).id,
        scope_type=scope,
        working_venue_ids=working,
        scope_venue_ids=scoped,
        now=now,
        expires_at=expires_at,
        ttl=ttl if expires_at is None else None,
    )


def service(ctx, *codes, pepper=PEPPER):
    return WorkforceInvitationService(
        ctx.session, AccessDecisionService(ctx.session), pepper, Codes(*codes)
    )


@pytest.mark.asyncio
async def test_generation_hmac_and_independent_persistence(invitation_context):
    ctx = invitation_context
    result = await service(ctx, "012345").create(request(
        ctx, ctx.targets[0], working=[ctx.venue1.id, ctx.venue1.id],
        scoped=[ctx.venue1.id, ctx.venue2.id, ctx.venue2.id],
        scope="explicit_venues",
    ))
    assert result.code == "012345" and result.code.isdigit() and len(result.code) == 6
    saved = await ctx.session.get(Invitation, result.invitation_id)
    assert saved.status == "pending"
    assert saved.created_by_account_id == ctx.owner.id
    assert saved.code_digest == hmac.new(
        PEPPER, b"012345", hashlib.sha256
    ).digest()
    assert len(saved.code_digest) == 32
    assert set((await ctx.session.execute(
        select(InvitationVenue.venue_id).where(
            InvitationVenue.invitation_id == result.invitation_id
        )
    )).scalars()) == {ctx.venue1.id}
    assert set((await ctx.session.execute(
        select(InvitationScopeVenue.venue_id).where(
            InvitationScopeVenue.invitation_id == result.invitation_id
        )
    )).scalars()) == {ctx.venue1.id, ctx.venue2.id}
    columns = set((await ctx.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='invitations'"
    ))).scalars())
    assert not {"code", "plaintext_code", "ciphertext"} & columns


@pytest.mark.asyncio
async def test_pepper_validation(invitation_context):
    ctx = invitation_context
    with pytest.raises(ValueError):
        service(ctx, "123456", pepper=b"")
    with pytest.raises(ValueError):
        service(ctx, "123456", pepper=b"x" * 31)


@pytest.mark.asyncio
async def test_authorization_modes(invitation_context):
    ctx = invitation_context
    await service(ctx, "100001").create(request(ctx, ctx.targets[1]))
    await service(ctx, "100002").create(request(
        ctx, ctx.targets[2], actor=ctx.company_manager
    ))
    await service(ctx, "100003").create(request(
        ctx, ctx.targets[3], actor=ctx.venue_manager,
        scope="working_venues", working=[ctx.venue1.id],
        access=ctx.venue_access,
    ))
    with pytest.raises(WorkforceInvitationForbidden):
        await service(ctx, "100004").create(request(
            ctx, ctx.targets[4], actor=ctx.venue_manager,
            scope="working_venues", working=[ctx.venue1.id, ctx.venue2.id],
            access=ctx.venue_access,
        ))
    with pytest.raises(WorkforceInvitationForbidden):
        await service(ctx, "100005").create(request(
            ctx, ctx.targets[5], actor=ctx.venue_manager,
            scope="company", access=ctx.company_access,
        ))
    with pytest.raises(WorkforceInvitationForbidden):
        await service(ctx, "100006").create(request(
            ctx, ctx.targets[6], actor=ctx.outsider,
            scope="working_venues", working=[ctx.venue1.id],
            access=ctx.venue_access,
        ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "100007").create(request(
            ctx, ctx.other_target, company=ctx.company.id
        ))


@pytest.mark.asyncio
async def test_business_objects_scope_and_venues(invitation_context):
    ctx = invitation_context
    attached = ctx.targets[7]
    attached.account_id = ctx.outsider.id
    await ctx.session.flush()
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200001").create(request(ctx, attached))
    for status in ("active", "suspended"):
        target = ctx.targets[8 if status == "active" else 9]
        target.employment_status = status
        await ctx.session.flush()
        with pytest.raises(InvalidWorkforceInvitation):
            await service(ctx, f"20000{2 if status == 'active' else 3}").create(
                request(ctx, target)
            )
    target = ctx.targets[10]
    target.employment_status = "terminated"
    target.terminated_at = NOW
    await ctx.session.flush()
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200004").create(request(ctx, target))

    ctx.position.is_active = False
    await ctx.session.flush()
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200005").create(request(ctx, ctx.targets[11]))
    ctx.position.is_active = True
    ctx.company_access.deleted_at = NOW
    await ctx.session.flush()
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200006").create(request(ctx, ctx.targets[12]))
    ctx.company_access.deleted_at = None
    await ctx.session.flush()

    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200007").create(request(
            ctx, ctx.targets[13], access=ctx.limited_access, scope="company"
        ))
    for bad_venue in (ctx.other_venue, ctx.closed, ctx.deleted):
        with pytest.raises(InvalidWorkforceInvitation):
            await service(ctx, "200008").create(request(
                ctx, ctx.targets[14], scope="working_venues",
                working=[bad_venue.id],
            ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200009").create(request(
            ctx, ctx.targets[15], scope="working_venues"
        ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200010").create(request(
            ctx, ctx.targets[16], scope="explicit_venues"
        ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "200011").create(request(
            ctx, ctx.targets[17], scope="self", scoped=[ctx.venue1.id]
        ))


@pytest.mark.asyncio
async def test_pending_and_code_collisions(invitation_context, monkeypatch):
    ctx = invitation_context
    collision_digest = hmac.new(PEPPER, b"300001", hashlib.sha256).digest()
    ctx.session.add(Invitation(
        id=uuid4(), company_id=ctx.company.id,
        employee_profile_id=ctx.targets[18].id, position_id=ctx.position.id,
        access_profile_id=ctx.company_access.id, scope_type="company",
        code_digest=collision_digest, status="pending",
        created_by_account_id=ctx.owner.id, expires_at=NOW + timedelta(hours=1),
        created_at=NOW, updated_at=NOW,
    ))
    await ctx.session.flush()
    result = await service(ctx, "300001", "300002").create(
        request(ctx, ctx.targets[19])
    )
    assert result.code == "300002"
    assert (await ctx.session.execute(text("SELECT 1"))).scalar_one() == 1

    with pytest.raises(PendingWorkforceInvitationExists):
        await service(ctx, "300003").create(request(ctx, ctx.targets[19]))

    expired = Invitation(
        id=uuid4(), company_id=ctx.company.id,
        employee_profile_id=ctx.targets[20].id, position_id=ctx.position.id,
        access_profile_id=ctx.company_access.id, scope_type="company",
        code_digest=hmac.new(PEPPER, b"300010", hashlib.sha256).digest(),
        status="pending", created_by_account_id=ctx.owner.id,
        expires_at=NOW - timedelta(minutes=1),
        created_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1),
    )
    ctx.session.add(expired)
    await ctx.session.flush()
    replacement = await service(ctx, "300011").create(
        request(ctx, ctx.targets[20])
    )
    await ctx.session.refresh(expired)
    assert expired.status == "expired" and expired.updated_at == NOW
    assert await ctx.session.get(Invitation, expired.id) is expired
    assert (await ctx.session.get(Invitation, replacement.invitation_id)).status == "pending"

    raced = service(ctx, "300004")
    async def missed_pending(_, __):
        return False
    monkeypatch.setattr(raced, "_expire_or_reject_pending", missed_pending)
    with pytest.raises(PendingWorkforceInvitationExists):
        await raced.create(request(ctx, ctx.targets[19]))

    exhausted = service(ctx, *(["300001"] * 10))
    with pytest.raises(InvitationCodeCollisionExhausted):
        await exhausted.create(request(ctx, ctx.targets[21]))


@pytest.mark.asyncio
async def test_time_validation(invitation_context):
    ctx = invitation_context
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "400001").create(request(
            ctx, ctx.targets[22], now=NOW.replace(tzinfo=None)
        ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "400002").create(request(
            ctx, ctx.targets[23], ttl=timedelta(minutes=4, seconds=59)
        ))
    with pytest.raises(InvalidWorkforceInvitation):
        await service(ctx, "400003").create(request(
            ctx, ctx.targets[24], ttl=timedelta(days=7, seconds=1)
        ))
    result = await service(ctx, "400004").create(request(
        ctx, ctx.targets[25], ttl=timedelta(minutes=5)
    ))
    assert result.expires_at == NOW + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_code_generator_requires_six_ascii_digits(invitation_context):
    ctx = invitation_context
    for index, bad_code in enumerate(
        ("١٢٣٤٥٦", "１２３４５６", "abc123", " 12345", "12345", "1234567")
    ):
        with pytest.raises(InvalidWorkforceInvitation):
            await service(ctx, bad_code).create(request(ctx, ctx.targets[26 + index % 4]))


def test_unknown_integrity_error_has_no_collision_constraint():
    unknown = RuntimeError("unrelated database integrity failure")
    error = IntegrityError("statement", {}, unknown)
    assert _postgres_constraint_name(error) is None
