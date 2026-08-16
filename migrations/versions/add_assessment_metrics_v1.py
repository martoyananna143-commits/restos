"""Add versioned assessment scoring and restaurant metric foundation.

Revision ID: add_assessment_metrics_v1
Revises: add_account_legal_acceptance_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_assessment_metrics_v1"
down_revision: Union[str, None] = "add_account_legal_acceptance_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assessment_assignments",
        sa.Column(
            "purpose",
            sa.String(length=30),
            server_default="employee_evaluation",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_assessment_assignments_purpose",
        "assessment_assignments",
        "purpose IN ('employee_evaluation', 'manager_measurement', 'operational_walkthrough')",
    )
    op.add_column(
        "assessment_attempt_answers",
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.add_column(
        "assessment_assignments",
        sa.Column("venue_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assessment_assignments_venue_company",
        "assessment_assignments",
        "venues",
        ["venue_id", "company_id"],
        ["id", "company_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_assessment_assignments_venue_status",
        "assessment_assignments",
        ["venue_id", "status"],
    )
    op.create_check_constraint(
        "ck_assessment_assignments_operational_venue",
        "assessment_assignments",
        "purpose != 'operational_walkthrough' OR venue_id IS NOT NULL",
    )
    op.create_unique_constraint(
        "uq_assessment_template_items_id_version",
        "assessment_template_items",
        ["id", "template_version_id"],
    )

    op.create_table(
        "assessment_metric_definitions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="active", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]{1,49}$'",
            name="ck_assessment_metric_definitions_code",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_assessment_metric_definitions_version"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_assessment_metric_definitions_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_metric_definitions"),
        sa.UniqueConstraint(
            "code",
            "version",
            name="uq_assessment_metric_definitions_code_version",
        ),
    )
    op.create_index(
        "uq_assessment_metric_definitions_active_code",
        "assessment_metric_definitions",
        ["code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.execute(
        sa.text(
            "INSERT INTO assessment_metric_definitions "
            "(id, code, version, title, description, status, created_at, updated_at) VALUES "
            "('10000000-0000-0000-0000-000000000001', 'taste', 1, 'Вкус', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000002', 'speed', 1, 'Скорость', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000003', 'order', 1, 'Порядок', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000004', 'service', 1, 'Сервис', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000005', 'people', 1, 'Люди', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000006', 'space', 1, 'Пространство', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000007', 'economics', 1, 'Экономика', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('10000000-0000-0000-0000-000000000008', 'food_safety', 1, 'Пищевая безопасность', NULL, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )

    op.create_table(
        "assessment_scoring_policies",
        sa.Column("template_version_id", sa.UUID(), nullable=False),
        sa.Column("algorithm", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "algorithm IN ('weighted_v1')",
            name="ck_assessment_scoring_policies_algorithm",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_assessment_scoring_policies_version"
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["assessment_template_versions.id"],
            name="fk_assessment_scoring_policies_template_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "template_version_id", name="pk_assessment_scoring_policies"
        ),
    )

    op.create_table(
        "assessment_item_metric_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_version_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("metric_definition_id", sa.UUID(), nullable=False),
        sa.Column("contribution_weight", sa.Numeric(18, 6), nullable=True),
        sa.Column(
            "direction", sa.String(length=20), server_default="positive", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "contribution_weight IS NULL OR contribution_weight > 0",
            name="ck_assessment_item_metric_mappings_weight",
        ),
        sa.CheckConstraint(
            "direction IN ('positive', 'inverse')",
            name="ck_assessment_item_metric_mappings_direction",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["assessment_template_versions.id"],
            name="fk_assessment_item_metric_mappings_template_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id", "template_version_id"],
            [
                "assessment_template_items.id",
                "assessment_template_items.template_version_id",
            ],
            name="fk_assessment_item_metric_mappings_item_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            ["assessment_metric_definitions.id"],
            name="fk_assessment_item_metric_mappings_metric",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_item_metric_mappings"),
        sa.UniqueConstraint(
            "item_id",
            "metric_definition_id",
            name="uq_assessment_item_metric_mappings_item_metric",
        ),
    )
    op.create_index(
        "ix_assessment_item_metric_mappings_version",
        "assessment_item_metric_mappings",
        ["template_version_id"],
    )
    op.create_index(
        "ix_assessment_item_metric_mappings_metric",
        "assessment_item_metric_mappings",
        ["metric_definition_id"],
    )

    op.create_table(
        "assessment_product_measurements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("venue_id", sa.UUID(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'completed')",
            name="ck_assessment_product_measurements_status",
        ),
        sa.CheckConstraint(
            "revision >= 0", name="ck_assessment_product_measurements_revision"
        ),
        sa.CheckConstraint(
            "((status = 'draft' AND completed_at IS NULL AND result_json IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL AND result_json IS NOT NULL))",
            name="ck_assessment_product_measurements_completion",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_assessment_product_measurements_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assessment_product_measurements_venue_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_product_measurements"),
    )
    op.create_index(
        "ix_assessment_product_measurements_company_time",
        "assessment_product_measurements",
        ["company_id", "started_at"],
    )
    op.create_index(
        "ix_assessment_product_measurements_venue_time",
        "assessment_product_measurements",
        ["venue_id", "started_at"],
    )
    op.create_table(
        "assessment_product_measurement_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("measurement_id", sa.UUID(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("position_type", sa.String(length=20), nullable=False),
        sa.Column("position_name", sa.String(length=255), nullable=False),
        sa.Column("taste_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("appearance_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("output_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("ticket_time_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity_unit", sa.String(length=20), nullable=False),
        sa.Column("planned_ticket_seconds", sa.Integer(), nullable=False),
        sa.Column("actual_ticket_seconds", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position_type IN ('dish', 'drink')",
            name="ck_assessment_product_measurement_items_type",
        ),
        sa.CheckConstraint(
            "taste_score BETWEEN 0 AND 3 AND appearance_score BETWEEN 0 AND 3 AND output_score BETWEEN 0 AND 3 AND ticket_time_score BETWEEN 0 AND 3",
            name="ck_assessment_product_measurement_items_scores",
        ),
        sa.CheckConstraint(
            "planned_quantity >= 0 AND actual_quantity >= 0 AND planned_ticket_seconds BETWEEN 0 AND 86400 AND actual_ticket_seconds BETWEEN 0 AND 86400",
            name="ck_assessment_product_measurement_items_values",
        ),
        sa.CheckConstraint(
            "length(btrim(position_name)) BETWEEN 1 AND 255",
            name="ck_assessment_product_measurement_items_name",
        ),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) <= 10000",
            name="ck_assessment_product_measurement_items_comment",
        ),
        sa.ForeignKeyConstraint(
            ["measurement_id"],
            ["assessment_product_measurements.id"],
            name="fk_assessment_product_measurement_items_measurement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_product_measurement_items"),
        sa.UniqueConstraint(
            "measurement_id",
            "sort_order",
            name="uq_assessment_product_measurement_items_order",
        ),
    )
    op.create_index(
        "ix_assessment_product_measurement_items_measurement",
        "assessment_product_measurement_items",
        ["measurement_id"],
    )

    op.create_table(
        "assessment_metric_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("venue_id", sa.UUID(), nullable=True),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("product_measurement_id", sa.UUID(), nullable=True),
        sa.Column("metric_definition_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("scoring_algorithm", sa.String(length=30), nullable=False),
        sa.Column("scoring_version", sa.Integer(), nullable=False),
        sa.Column("numerator", sa.Numeric(24, 8), nullable=False),
        sa.Column("denominator", sa.Numeric(24, 8), nullable=False),
        sa.Column("score_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("coverage", sa.Numeric(8, 6), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "critical_failure_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "stop_factor_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(attempt_id, product_measurement_id) = 1",
            name="ck_assessment_metric_observations_one_source",
        ),
        sa.CheckConstraint(
            "source_type IN ('evaluation', 'measurement', 'walkthrough', "
            "'checklist', 'test', 'survey', 'attestation')",
            name="ck_assessment_metric_observations_source_type",
        ),
        sa.CheckConstraint(
            "denominator > 0",
            name="ck_assessment_metric_observations_denominator",
        ),
        sa.CheckConstraint(
            "score_percent >= 0 AND score_percent <= 100",
            name="ck_assessment_metric_observations_score",
        ),
        sa.CheckConstraint(
            "coverage >= 0 AND coverage <= 1",
            name="ck_assessment_metric_observations_coverage",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'insufficient_coverage')",
            name="ck_assessment_metric_observations_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_assessment_metric_observations_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assessment_metric_observations_venue_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            name="fk_assessment_metric_observations_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_measurement_id"],
            ["assessment_product_measurements.id"],
            name="fk_assessment_metric_observations_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            ["assessment_metric_definitions.id"],
            name="fk_assessment_metric_observations_metric",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_metric_observations"),
    )
    op.create_index(
        "uq_assessment_metric_observations_attempt_metric",
        "assessment_metric_observations",
        ["attempt_id", "metric_definition_id"],
        unique=True,
        postgresql_where=sa.text("attempt_id IS NOT NULL"),
    )
    op.create_index(
        "uq_assessment_metric_observations_product_metric",
        "assessment_metric_observations",
        ["product_measurement_id", "metric_definition_id"],
        unique=True,
        postgresql_where=sa.text("product_measurement_id IS NOT NULL"),
    )
    op.create_index(
        "ix_assessment_metric_observations_company_metric_time",
        "assessment_metric_observations",
        ["company_id", "metric_definition_id", "observed_at"],
    )
    op.create_index(
        "ix_assessment_metric_observations_venue_metric_time",
        "assessment_metric_observations",
        ["venue_id", "metric_definition_id", "observed_at"],
    )

    op.create_table(
        "assessment_aggregation_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("metric_definition_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_assessment_aggregation_policies_version"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_assessment_aggregation_policies_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_assessment_aggregation_policies_period",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_assessment_aggregation_policies_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            ["assessment_metric_definitions.id"],
            name="fk_assessment_aggregation_policies_metric",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_aggregation_policies"),
        sa.UniqueConstraint(
            "company_id",
            "metric_definition_id",
            "version",
            name="uq_assessment_aggregation_policies_company_metric_version",
        ),
    )
    op.create_index(
        "uq_assessment_aggregation_policies_active",
        "assessment_aggregation_policies",
        ["company_id", "metric_definition_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "assessment_template_import_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_version_id", sa.UUID(), nullable=False),
        sa.Column("source_filename", sa.String(length=500), nullable=False),
        sa.Column("provenance", sa.String(length=50), nullable=False),
        sa.Column("source_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("manifest_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(source_sha256) = 32",
            name="ck_assessment_template_import_sources_sha",
        ),
        sa.CheckConstraint(
            "provenance = 'read_only_methodology_source'",
            name="ck_assessment_template_import_sources_provenance",
        ),
        sa.CheckConstraint(
            "octet_length(manifest_sha256) = 32",
            name="ck_assessment_template_import_sources_manifest_sha",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["assessment_template_versions.id"],
            name="fk_assessment_template_import_sources_template_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assessment_template_import_sources"),
        sa.UniqueConstraint(
            "template_version_id",
            "source_sha256",
            name="uq_assessment_template_import_sources_version_sha",
        ),
    )
    op.create_index(
        "ix_assessment_template_import_sources_version",
        "assessment_template_import_sources",
        ["template_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assessment_template_import_sources_version",
        table_name="assessment_template_import_sources",
    )
    op.drop_table("assessment_template_import_sources")
    op.drop_index(
        "uq_assessment_aggregation_policies_active",
        table_name="assessment_aggregation_policies",
    )
    op.drop_table("assessment_aggregation_policies")
    op.drop_index(
        "ix_assessment_metric_observations_venue_metric_time",
        table_name="assessment_metric_observations",
    )
    op.drop_index(
        "ix_assessment_metric_observations_company_metric_time",
        table_name="assessment_metric_observations",
    )
    op.drop_table("assessment_metric_observations")
    op.drop_index(
        "ix_assessment_product_measurement_items_measurement",
        table_name="assessment_product_measurement_items",
    )
    op.drop_table("assessment_product_measurement_items")
    op.drop_index(
        "ix_assessment_product_measurements_venue_time",
        table_name="assessment_product_measurements",
    )
    op.drop_index(
        "ix_assessment_product_measurements_company_time",
        table_name="assessment_product_measurements",
    )
    op.drop_table("assessment_product_measurements")
    op.drop_index(
        "ix_assessment_item_metric_mappings_metric",
        table_name="assessment_item_metric_mappings",
    )
    op.drop_index(
        "ix_assessment_item_metric_mappings_version",
        table_name="assessment_item_metric_mappings",
    )
    op.drop_table("assessment_item_metric_mappings")
    op.drop_table("assessment_scoring_policies")
    op.drop_constraint(
        "uq_assessment_template_items_id_version",
        "assessment_template_items",
        type_="unique",
    )
    op.drop_index(
        "uq_assessment_metric_definitions_active_code",
        table_name="assessment_metric_definitions",
    )
    op.drop_table("assessment_metric_definitions")
    op.drop_index(
        "ix_assessment_assignments_venue_status",
        table_name="assessment_assignments",
    )
    op.drop_constraint(
        "fk_assessment_assignments_venue_company",
        "assessment_assignments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_assessment_assignments_operational_venue",
        "assessment_assignments",
        type_="check",
    )
    op.drop_column("assessment_assignments", "venue_id")
    op.drop_constraint(
        "ck_assessment_assignments_purpose",
        "assessment_assignments",
        type_="check",
    )
    op.drop_column("assessment_assignments", "purpose")
    op.drop_column("assessment_attempt_answers", "comment")
