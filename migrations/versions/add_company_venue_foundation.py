"""Add company and venue foundation tables.

Revision ID: add_company_venue_foundation
Revises: add_account_auth_foundation
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_company_venue_foundation"
down_revision: Union[str, None] = "add_account_auth_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("tax_id", sa.String(length=100), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("locale", sa.String(length=35), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
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
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_companies_code_slug",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_companies_status",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_companies_owner_account_id", "companies", ["owner_account_id"]
    )
    op.create_index(
        "uq_companies_active_code",
        "companies",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "venues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legacy_organization_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("concept", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
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
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_venues_code_slug",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'temporarily_closed', 'closed')",
            name="ck_venues_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legacy_organization_id", name="uq_venues_legacy_organization_id"
        ),
    )
    op.create_index("ix_venues_company_id", "venues", ["company_id"])
    op.create_index(
        "ix_venues_legacy_organization_id", "venues", ["legacy_organization_id"]
    )
    op.create_index(
        "uq_venues_active_company_code",
        "venues",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_venues_active_company_code", table_name="venues")
    op.drop_index("ix_venues_legacy_organization_id", table_name="venues")
    op.drop_index("ix_venues_company_id", table_name="venues")
    op.drop_table("venues")
    op.drop_index("uq_companies_active_code", table_name="companies")
    op.drop_index("ix_companies_owner_account_id", table_name="companies")
    op.drop_table("companies")
