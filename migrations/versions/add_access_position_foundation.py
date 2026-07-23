"""Add access profile, permission, and position foundation tables.

Revision ID: add_access_position_foundation
Revises: add_company_venue_foundation
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_access_position_foundation"
down_revision: Union[str, None] = "add_company_venue_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("maximum_scope", sa.String(length=30), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_access_profiles_code_slug",
        ),
        sa.CheckConstraint(
            "maximum_scope IN ('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_access_profiles_maximum_scope",
        ),
        sa.CheckConstraint("version >= 1", name="ck_access_profiles_version"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_access_profiles_id_company"),
    )
    op.create_index(
        "ix_access_profiles_company_active",
        "access_profiles",
        ["company_id", "is_active"],
    )
    op.create_index(
        "uq_access_profiles_active_company_code",
        "access_profiles",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND is_active"),
    )

    op.create_table(
        "access_profile_permissions",
        sa.Column("access_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_code", sa.String(length=150), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "permission_code = lower(permission_code) "
            "AND permission_code ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){1,2}$'",
            name="ck_access_profile_permissions_code",
        ),
        sa.ForeignKeyConstraint(
            ["access_profile_id"], ["access_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("access_profile_id", "permission_code"),
    )
    op.create_index(
        "ix_access_profile_permissions_code",
        "access_profile_permissions",
        ["permission_code"],
    )

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_access_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
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
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_positions_code_slug",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_positions_sort_order"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["default_access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_positions_default_profile_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_positions_company_active", "positions", ["company_id", "is_active"]
    )
    op.create_index(
        "ix_positions_default_access_profile_id",
        "positions",
        ["default_access_profile_id"],
    )
    op.create_index(
        "uq_positions_active_company_code",
        "positions",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_positions_active_company_code", table_name="positions")
    op.drop_index("ix_positions_default_access_profile_id", table_name="positions")
    op.drop_index("ix_positions_company_active", table_name="positions")
    op.drop_table("positions")
    op.drop_index(
        "ix_access_profile_permissions_code", table_name="access_profile_permissions"
    )
    op.drop_table("access_profile_permissions")
    op.drop_index(
        "uq_access_profiles_active_company_code", table_name="access_profiles"
    )
    op.drop_index("ix_access_profiles_company_active", table_name="access_profiles")
    op.drop_table("access_profiles")
