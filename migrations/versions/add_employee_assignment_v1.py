"""Add employee profile and assignment foundation tables.

Revision ID: add_employee_assignment_v1
Revises: add_access_position_foundation
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_employee_assignment_v1"
down_revision: Union[str, None] = "add_access_position_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_positions_id_company", "positions", ["id", "company_id"])
    op.create_unique_constraint("uq_venues_id_company", "venues", ["id", "company_id"])

    op.create_table(
        "employee_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("employment_status", sa.String(length=20), nullable=False),
        sa.Column("hired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            "employment_status IN ('invited', 'active', 'suspended', 'terminated')",
            name="ck_employee_profiles_status",
        ),
        sa.CheckConstraint(
            "((employment_status = 'terminated' AND terminated_at IS NOT NULL) "
            "OR (employment_status <> 'terminated' AND terminated_at IS NULL))",
            name="ck_employee_profiles_termination_state",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_employee_profiles_id_company"),
    )
    op.create_index(
        "ix_employee_profiles_company_status",
        "employee_profiles",
        ["company_id", "employment_status"],
    )
    op.create_index(
        "uq_employee_profiles_active_company_account",
        "employee_profiles",
        ["company_id", "account_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND account_id IS NOT NULL"),
    )

    op.create_table(
        "employee_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("legacy_employee_id", sa.Integer(), nullable=True),
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
            name="ck_employee_assignments_scope_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'ended', 'revoked')",
            name="ck_employee_assignments_status",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name="ck_employee_assignments_dates",
        ),
        sa.CheckConstraint(
            "status <> 'ended' OR ends_at IS NOT NULL",
            name="ck_employee_assignments_ended_at",
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR (revoked_at IS NOT NULL "
            "AND revoked_by_account_id IS NOT NULL)",
            name="ck_employee_assignments_revoked_state",
        ),
        sa.CheckConstraint(
            "status = 'revoked' OR (revoked_at IS NULL "
            "AND revoked_by_account_id IS NULL AND revoke_reason IS NULL)",
            name="ck_employee_assignments_non_revoked_state",
        ),
        sa.CheckConstraint(
            "NOT is_primary OR status = 'active'",
            name="ck_employee_assignments_primary_active",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_employee_assignments_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_employee_assignments_position_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_employee_assignments_access_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_employee_assignments_id_company"),
        sa.UniqueConstraint(
            "legacy_employee_id", name="uq_employee_assignments_legacy_employee_id"
        ),
    )
    op.create_index(
        "ix_employee_assignments_company_id", "employee_assignments", ["company_id"]
    )
    op.create_index(
        "ix_employee_assignments_employee_profile_id",
        "employee_assignments",
        ["employee_profile_id"],
    )
    op.create_index(
        "ix_employee_assignments_position_id", "employee_assignments", ["position_id"]
    )
    op.create_index(
        "ix_employee_assignments_access_profile_id",
        "employee_assignments",
        ["access_profile_id"],
    )
    op.create_index(
        "ix_employee_assignments_status", "employee_assignments", ["status"]
    )
    op.create_index(
        "ix_employee_assignments_legacy_employee_id",
        "employee_assignments",
        ["legacy_employee_id"],
    )
    op.create_index(
        "uq_employee_assignments_active_primary_profile",
        "employee_assignments",
        ["employee_profile_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status = 'active' AND is_primary"
        ),
    )

    op.create_table(
        "assignment_venues",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_assignment_venues_assignment_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assignment_venues_venue_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("assignment_id", "venue_id"),
    )
    op.create_index(
        "ix_assignment_venues_venue_assignment",
        "assignment_venues",
        ["venue_id", "assignment_id"],
    )

    op.create_table(
        "assignment_scope_venues",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_assignment_scope_venues_assignment_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assignment_scope_venues_venue_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("assignment_id", "venue_id"),
    )
    op.create_index(
        "ix_assignment_scope_venues_venue_assignment",
        "assignment_scope_venues",
        ["venue_id", "assignment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assignment_scope_venues_venue_assignment",
        table_name="assignment_scope_venues",
    )
    op.drop_table("assignment_scope_venues")
    op.drop_index(
        "ix_assignment_venues_venue_assignment", table_name="assignment_venues"
    )
    op.drop_table("assignment_venues")
    op.drop_index(
        "uq_employee_assignments_active_primary_profile",
        table_name="employee_assignments",
    )
    op.drop_index(
        "ix_employee_assignments_legacy_employee_id", table_name="employee_assignments"
    )
    op.drop_index("ix_employee_assignments_status", table_name="employee_assignments")
    op.drop_index(
        "ix_employee_assignments_access_profile_id", table_name="employee_assignments"
    )
    op.drop_index(
        "ix_employee_assignments_position_id", table_name="employee_assignments"
    )
    op.drop_index(
        "ix_employee_assignments_employee_profile_id", table_name="employee_assignments"
    )
    op.drop_index(
        "ix_employee_assignments_company_id", table_name="employee_assignments"
    )
    op.drop_table("employee_assignments")
    op.drop_index(
        "uq_employee_profiles_active_company_account", table_name="employee_profiles"
    )
    op.drop_index(
        "ix_employee_profiles_company_status", table_name="employee_profiles"
    )
    op.drop_table("employee_profiles")
    op.drop_constraint("uq_venues_id_company", "venues", type_="unique")
    op.drop_constraint("uq_positions_id_company", "positions", type_="unique")
