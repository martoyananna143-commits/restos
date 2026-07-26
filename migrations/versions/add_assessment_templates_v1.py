"""Add universal assessment-template library foundation.

Revision ID: add_assessment_templates_v1
Revises: add_device_proof_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_assessment_templates_v1"
down_revision: Union[str, None] = "add_device_proof_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLUG = "^[a-z0-9]+(-[a-z0-9]+)*$"


def _timestamps(*, soft_delete: bool = False) -> list[sa.Column]:
    columns = [
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
    ]
    if soft_delete:
        columns.append(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def upgrade() -> None:
    op.create_table(
        "assessment_methodologies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(soft_delete=True),
        sa.CheckConstraint(
            "owner_type IN ('system', 'company')",
            name="ck_assessment_methodologies_owner_type",
        ),
        sa.CheckConstraint(
            "((owner_type = 'system' AND company_id IS NULL) OR "
            "(owner_type = 'company' AND company_id IS NOT NULL))",
            name="ck_assessment_methodologies_owner_context",
        ),
        sa.CheckConstraint(
            f"code ~ '{_SLUG}'",
            name="ck_assessment_methodologies_code",
        ),
        sa.CheckConstraint("version >= 1", name="ck_assessment_methodologies_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_assessment_methodologies_status",
        ),
        sa.CheckConstraint(
            "((status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired') AND published_at IS NOT NULL))",
            name="ck_assessment_methodologies_publication",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_methodologies_company_id",
        "assessment_methodologies",
        ["company_id"],
    )
    op.create_index(
        "uq_assessment_methodologies_system_code_version",
        "assessment_methodologies",
        ["code", "version"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND owner_type = 'system'"
        ),
    )
    op.create_index(
        "uq_assessment_methodologies_company_code_version",
        "assessment_methodologies",
        ["company_id", "code", "version"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND owner_type = 'company'"
        ),
    )

    # source_library_version_id is added as a foreign key after versions exist.
    op.create_table(
        "assessment_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source_library_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(soft_delete=True),
        sa.CheckConstraint(
            "scope IN ('library', 'company')",
            name="ck_assessment_templates_scope",
        ),
        sa.CheckConstraint(
            "((scope = 'library' AND company_id IS NULL) OR "
            "(scope = 'company' AND company_id IS NOT NULL))",
            name="ck_assessment_templates_scope_context",
        ),
        sa.CheckConstraint(
            "source_library_version_id IS NULL OR scope = 'company'",
            name="ck_assessment_templates_source_scope",
        ),
        sa.CheckConstraint(
            f"code ~ '{_SLUG}'",
            name="ck_assessment_templates_code",
        ),
        sa.CheckConstraint(
            "activity_type IN ('evaluation', 'measurement', 'walkthrough', "
            "'checklist', 'test', 'survey', 'attestation')",
            name="ck_assessment_templates_activity_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_assessment_templates_status",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_templates_company_id",
        "assessment_templates",
        ["company_id"],
    )
    op.create_index(
        "ix_assessment_templates_source_library_version_id",
        "assessment_templates",
        ["source_library_version_id"],
    )
    op.create_index(
        "uq_assessment_templates_active_library_code",
        "assessment_templates",
        ["code"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status = 'active' AND scope = 'library'"
        ),
    )
    op.create_index(
        "uq_assessment_templates_active_company_code",
        "assessment_templates",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status = 'active' AND scope = 'company'"
        ),
    )

    op.create_table(
        "assessment_template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("methodology_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_description", sa.Text(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_assessment_template_versions_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_assessment_template_versions_status",
        ),
        sa.CheckConstraint(
            "((status = 'published' AND published_at IS NOT NULL) OR "
            "(status = 'draft' AND published_at IS NULL) OR status = 'archived')",
            name="ck_assessment_template_versions_publication",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["assessment_templates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["methodology_id"], ["assessment_methodologies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "version",
            name="uq_assessment_template_versions_template_version",
        ),
        sa.UniqueConstraint(
            "id",
            "template_id",
            name="uq_assessment_template_versions_id_template",
        ),
    )
    op.create_index(
        "ix_assessment_template_versions_template_status",
        "assessment_template_versions",
        ["template_id", "status"],
    )
    op.create_foreign_key(
        "fk_assessment_templates_source_library_version",
        "assessment_templates",
        "assessment_template_versions",
        ["source_library_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "assessment_template_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("section_kind", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"code ~ '{_SLUG}'",
            name="ck_assessment_template_sections_code",
        ),
        sa.CheckConstraint(
            "section_kind IN ('section', 'zone', 'group')",
            name="ck_assessment_template_sections_kind",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_sections_sort_order",
        ),
        sa.CheckConstraint(
            "weight IS NULL OR weight >= 0",
            name="ck_assessment_template_sections_weight",
        ),
        sa.CheckConstraint(
            "parent_section_id IS NULL OR parent_section_id <> id",
            name="ck_assessment_template_sections_not_self_parent",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["assessment_template_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_section_id", "template_version_id"],
            [
                "assessment_template_sections.id",
                "assessment_template_sections.template_version_id",
            ],
            name="fk_assessment_template_sections_parent_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_version_id",
            "code",
            name="uq_assessment_template_sections_version_code",
        ),
        sa.UniqueConstraint(
            "id",
            "template_version_id",
            name="uq_assessment_template_sections_id_version",
        ),
    )
    op.create_index(
        "ix_assessment_template_sections_version_sort",
        "assessment_template_sections",
        ["template_version_id", "sort_order"],
    )

    op.create_table(
        "assessment_template_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("response_type", sa.String(length=30), nullable=False),
        sa.Column(
            "is_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("min_value", sa.Numeric(), nullable=True),
        sa.Column("max_value", sa.Numeric(), nullable=True),
        sa.Column("passing_value", sa.Numeric(), nullable=True),
        sa.Column("evidence_mode", sa.String(length=30), nullable=False),
        sa.Column("criticality", sa.String(length=20), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            f"code ~ '{_SLUG}'",
            name="ck_assessment_template_items_code",
        ),
        sa.CheckConstraint(
            "response_type IN ('boolean', 'score', 'integer', 'decimal', 'text', "
            "'single_choice', 'multi_choice', 'date', 'time')",
            name="ck_assessment_template_items_response_type",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_items_sort_order",
        ),
        sa.CheckConstraint(
            "weight IS NULL OR weight >= 0",
            name="ck_assessment_template_items_weight",
        ),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_assessment_template_items_value_range",
        ),
        sa.CheckConstraint(
            "passing_value IS NULL OR "
            "((min_value IS NULL OR passing_value >= min_value) AND "
            "(max_value IS NULL OR passing_value <= max_value))",
            name="ck_assessment_template_items_passing_range",
        ),
        sa.CheckConstraint(
            "evidence_mode IN ('none', 'optional_photo', 'required_photo', "
            "'optional_comment', 'required_comment', 'photo_and_comment')",
            name="ck_assessment_template_items_evidence_mode",
        ),
        sa.CheckConstraint(
            "criticality IN ('normal', 'critical', 'stop_factor')",
            name="ck_assessment_template_items_criticality",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["assessment_template_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "template_version_id"],
            [
                "assessment_template_sections.id",
                "assessment_template_sections.template_version_id",
            ],
            name="fk_assessment_template_items_section_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_version_id",
            "code",
            name="uq_assessment_template_items_version_code",
        ),
    )
    op.create_index(
        "ix_assessment_template_items_section_sort",
        "assessment_template_items",
        ["section_id", "sort_order"],
    )
    op.create_index(
        "ix_assessment_template_items_version_sort",
        "assessment_template_items",
        ["template_version_id", "sort_order"],
    )

    op.create_table(
        "assessment_template_item_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("numeric_value", sa.Numeric(), nullable=True),
        sa.Column(
            "is_disqualifying",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            f"code ~ '{_SLUG}'",
            name="ck_assessment_template_item_options_code",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_item_options_sort_order",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["assessment_template_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "code",
            name="uq_assessment_template_item_options_item_code",
        ),
    )
    op.create_index(
        "ix_assessment_template_item_options_item_sort",
        "assessment_template_item_options",
        ["item_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_table("assessment_template_item_options")
    op.drop_table("assessment_template_items")
    op.drop_table("assessment_template_sections")
    op.drop_constraint(
        "fk_assessment_templates_source_library_version",
        "assessment_templates",
        type_="foreignkey",
    )
    op.drop_table("assessment_template_versions")
    op.drop_table("assessment_templates")
    op.drop_table("assessment_methodologies")
