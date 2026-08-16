"""Versioned scoring, metric mapping, observation, and import provenance."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class AssessmentMetricDefinition(Base, TimestampMixin):
    """Immutable version of one canonical restaurant metric."""

    __tablename__ = "assessment_metric_definitions"
    __table_args__ = (
        UniqueConstraint(
            "code",
            "version",
            name="uq_assessment_metric_definitions_code_version",
        ),
        CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]{1,49}$'",
            name="ck_assessment_metric_definitions_code",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_metric_definitions_version",
        ),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_assessment_metric_definitions_status",
        ),
        Index(
            "uq_assessment_metric_definitions_active_code",
            "code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )


class AssessmentScoringPolicy(Base, TimestampMixin):
    """Immutable scoring configuration owned by a template version."""

    __tablename__ = "assessment_scoring_policies"
    __table_args__ = (
        CheckConstraint(
            "algorithm IN ('weighted_v1')",
            name="ck_assessment_scoring_policies_algorithm",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_scoring_policies_version",
        ),
    )

    template_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_template_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    algorithm: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class AssessmentItemMetricMapping(Base, TimestampMixin):
    """Immutable mapping from one versioned criterion to a canonical metric."""

    __tablename__ = "assessment_item_metric_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "template_version_id"],
            [
                "assessment_template_items.id",
                "assessment_template_items.template_version_id",
            ],
            name="fk_assessment_item_metric_mappings_item_version",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "item_id",
            "metric_definition_id",
            name="uq_assessment_item_metric_mappings_item_metric",
        ),
        CheckConstraint(
            "contribution_weight IS NULL OR contribution_weight > 0",
            name="ck_assessment_item_metric_mappings_weight",
        ),
        CheckConstraint(
            "direction IN ('positive', 'inverse')",
            name="ck_assessment_item_metric_mappings_direction",
        ),
        Index(
            "ix_assessment_item_metric_mappings_version",
            "template_version_id",
        ),
        Index(
            "ix_assessment_item_metric_mappings_metric",
            "metric_definition_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    metric_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_metric_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contribution_weight: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="positive", server_default="positive"
    )


class AssessmentMetricObservation(Base, TimestampMixin):
    """Idempotent metric contribution materialized from one submitted attempt."""

    __tablename__ = "assessment_metric_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assessment_metric_observations_venue_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(attempt_id, product_measurement_id) = 1",
            name="ck_assessment_metric_observations_one_source",
        ),
        CheckConstraint(
            "source_type IN ('evaluation', 'measurement', 'walkthrough', "
            "'checklist', 'test', 'survey', 'attestation')",
            name="ck_assessment_metric_observations_source_type",
        ),
        CheckConstraint(
            "denominator > 0",
            name="ck_assessment_metric_observations_denominator",
        ),
        CheckConstraint(
            "score_percent >= 0 AND score_percent <= 100",
            name="ck_assessment_metric_observations_score",
        ),
        CheckConstraint(
            "coverage >= 0 AND coverage <= 1",
            name="ck_assessment_metric_observations_coverage",
        ),
        CheckConstraint(
            "status IN ('complete', 'insufficient_coverage')",
            name="ck_assessment_metric_observations_status",
        ),
        Index(
            "ix_assessment_metric_observations_company_metric_time",
            "company_id",
            "metric_definition_id",
            "observed_at",
        ),
        Index(
            "ix_assessment_metric_observations_venue_metric_time",
            "venue_id",
            "metric_definition_id",
            "observed_at",
        ),
        Index(
            "uq_assessment_metric_observations_attempt_metric",
            "attempt_id",
            "metric_definition_id",
            unique=True,
            postgresql_where=text("attempt_id IS NOT NULL"),
        ),
        Index(
            "uq_assessment_metric_observations_product_metric",
            "product_measurement_id",
            "metric_definition_id",
            unique=True,
            postgresql_where=text("product_measurement_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    venue_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    attempt_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    product_measurement_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_product_measurements.id", ondelete="RESTRICT"),
        nullable=True,
    )
    metric_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_metric_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scoring_algorithm: Mapped[str] = mapped_column(String(30), nullable=False)
    scoring_version: Mapped[int] = mapped_column(Integer, nullable=False)
    numerator: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    denominator: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    score_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    coverage: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    critical_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    stop_factor_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    detail_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AssessmentAggregationPolicy(Base, TimestampMixin):
    """Company-owned versioned formula; draft policies do not create composites."""

    __tablename__ = "assessment_aggregation_policies"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "metric_definition_id",
            "version",
            name="uq_assessment_aggregation_policies_company_metric_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_aggregation_policies_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_assessment_aggregation_policies_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_assessment_aggregation_policies_period",
        ),
        Index(
            "uq_assessment_aggregation_policies_active",
            "company_id",
            "metric_definition_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_metric_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AssessmentTemplateImportSource(Base, TimestampMixin):
    """Read-only provenance for one source workbook used by a template version."""

    __tablename__ = "assessment_template_import_sources"
    __table_args__ = (
        UniqueConstraint(
            "template_version_id",
            "source_sha256",
            name="uq_assessment_template_import_sources_version_sha",
        ),
        CheckConstraint(
            "octet_length(source_sha256) = 32",
            name="ck_assessment_template_import_sources_sha",
        ),
        CheckConstraint(
            "provenance = 'read_only_methodology_source'",
            name="ck_assessment_template_import_sources_provenance",
        ),
        CheckConstraint(
            "octet_length(manifest_sha256) = 32",
            name="ck_assessment_template_import_sources_manifest_sha",
        ),
        Index(
            "ix_assessment_template_import_sources_version",
            "template_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    provenance: Mapped[str] = mapped_column(String(50), nullable=False)
    source_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    manifest_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AssessmentProductMeasurement(Base, TimestampMixin):
    """One repeatable product taste/speed measurement session."""

    __tablename__ = "assessment_product_measurements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assessment_product_measurements_venue_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('draft', 'completed')",
            name="ck_assessment_product_measurements_status",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_assessment_product_measurements_revision",
        ),
        CheckConstraint(
            "((status = 'draft' AND completed_at IS NULL AND result_json IS NULL) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND result_json IS NOT NULL))",
            name="ck_assessment_product_measurements_completion",
        ),
        Index(
            "ix_assessment_product_measurements_company_time",
            "company_id",
            "started_at",
        ),
        Index(
            "ix_assessment_product_measurements_venue_time",
            "venue_id",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class AssessmentProductMeasurementItem(Base, TimestampMixin):
    """One dynamically added dish or drink in a product measurement."""

    __tablename__ = "assessment_product_measurement_items"
    __table_args__ = (
        UniqueConstraint(
            "measurement_id",
            "sort_order",
            name="uq_assessment_product_measurement_items_order",
        ),
        CheckConstraint(
            "position_type IN ('dish', 'drink')",
            name="ck_assessment_product_measurement_items_type",
        ),
        CheckConstraint(
            "taste_score BETWEEN 0 AND 3 AND appearance_score BETWEEN 0 AND 3 "
            "AND output_score BETWEEN 0 AND 3 AND ticket_time_score BETWEEN 0 AND 3",
            name="ck_assessment_product_measurement_items_scores",
        ),
        CheckConstraint(
            "planned_quantity >= 0 AND actual_quantity >= 0 "
            "AND planned_ticket_seconds BETWEEN 0 AND 86400 "
            "AND actual_ticket_seconds BETWEEN 0 AND 86400",
            name="ck_assessment_product_measurement_items_values",
        ),
        CheckConstraint(
            "length(btrim(position_name)) BETWEEN 1 AND 255",
            name="ck_assessment_product_measurement_items_name",
        ),
        CheckConstraint(
            "comment IS NULL OR length(comment) <= 10000",
            name="ck_assessment_product_measurement_items_comment",
        ),
        Index(
            "ix_assessment_product_measurement_items_measurement",
            "measurement_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    measurement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_product_measurements.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    position_type: Mapped[str] = mapped_column(String(20), nullable=False)
    position_name: Mapped[str] = mapped_column(String(255), nullable=False)
    taste_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    appearance_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    output_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    ticket_time_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    actual_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    planned_ticket_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_ticket_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
