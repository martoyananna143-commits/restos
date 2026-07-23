"""Add secure workforce invitation foundation tables.

Revision ID: add_invitation_foundation
Revises: add_employee_assignment_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_invitation_foundation"
down_revision: Union[str, None] = "add_employee_assignment_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("code_digest", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_invitations_scope_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'cancelled', 'expired')",
            name="ck_invitations_status",
        ),
        sa.CheckConstraint(
            "octet_length(code_digest) = 32",
            name="ck_invitations_code_digest_length",
        ),
        sa.CheckConstraint(
            "("
            "(status = 'pending' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL) OR "
            "(status = 'accepted' AND accepted_by_account_id IS NOT NULL "
            "AND accepted_assignment_id IS NOT NULL AND accepted_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL) OR "
            "(status = 'cancelled' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NOT NULL AND cancelled_by_account_id IS NOT NULL) OR "
            "(status = 'expired' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL)"
            ")",
            name="ck_invitations_state",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_invitations_expiry",
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR (accepted_at >= created_at "
            "AND accepted_at <= expires_at)",
            name="ck_invitations_accepted_at",
        ),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at",
            name="ck_invitations_cancelled_at",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_invitations_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_invitations_position_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_invitations_access_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_invitations_assignment_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_invitations_id_company"),
    )
    op.create_index("ix_invitations_company_id", "invitations", ["company_id"])
    op.create_index(
        "ix_invitations_employee_profile_id", "invitations", ["employee_profile_id"]
    )
    op.create_index("ix_invitations_status", "invitations", ["status"])
    op.create_index("ix_invitations_expires_at", "invitations", ["expires_at"])
    op.create_index(
        "ix_invitations_created_by_account_id",
        "invitations",
        ["created_by_account_id"],
    )
    op.create_index(
        "uq_invitations_active_code_digest",
        "invitations",
        ["code_digest"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_invitations_pending_employee_profile",
        "invitations",
        ["employee_profile_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_invitations_accepted_assignment",
        "invitations",
        ["accepted_assignment_id"],
        unique=True,
        postgresql_where=sa.text("accepted_assignment_id IS NOT NULL"),
    )

    op.create_table(
        "invitation_venues",
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "company_id"],
            ["invitations.id", "invitations.company_id"],
            name="fk_invitation_venues_invitation_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_invitation_venues_venue_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invitation_id", "venue_id"),
    )
    op.create_index(
        "ix_invitation_venues_venue_invitation",
        "invitation_venues",
        ["venue_id", "invitation_id"],
    )

    op.create_table(
        "invitation_scope_venues",
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "company_id"],
            ["invitations.id", "invitations.company_id"],
            name="fk_invitation_scope_venues_invitation_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_invitation_scope_venues_venue_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("invitation_id", "venue_id"),
    )
    op.create_index(
        "ix_invitation_scope_venues_venue_invitation",
        "invitation_scope_venues",
        ["venue_id", "invitation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invitation_scope_venues_venue_invitation",
        table_name="invitation_scope_venues",
    )
    op.drop_table("invitation_scope_venues")
    op.drop_index(
        "ix_invitation_venues_venue_invitation", table_name="invitation_venues"
    )
    op.drop_table("invitation_venues")
    op.drop_index(
        "uq_invitations_accepted_assignment", table_name="invitations"
    )
    op.drop_index(
        "uq_invitations_pending_employee_profile", table_name="invitations"
    )
    op.drop_index("uq_invitations_active_code_digest", table_name="invitations")
    op.drop_index("ix_invitations_created_by_account_id", table_name="invitations")
    op.drop_index("ix_invitations_expires_at", table_name="invitations")
    op.drop_index("ix_invitations_status", table_name="invitations")
    op.drop_index("ix_invitations_employee_profile_id", table_name="invitations")
    op.drop_index("ix_invitations_company_id", table_name="invitations")
    op.drop_table("invitations")
