"""Additive universal template library schema.

Published methodology and template versions are immutable domain artifacts.
Database state makes publication explicit; mutation prevention belongs to the
future template service. A company adaptation references the exact library
version and its methodology instead of copying methodology text into mutable
company-owned content.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


_SLUG_CHECK = "^[a-z0-9]+(-[a-z0-9]+)*$"


class AssessmentMethodology(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "assessment_methodologies"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('system', 'company')",
            name="ck_assessment_methodologies_owner_type",
        ),
        CheckConstraint(
            "((owner_type = 'system' AND company_id IS NULL) OR "
            "(owner_type = 'company' AND company_id IS NOT NULL))",
            name="ck_assessment_methodologies_owner_context",
        ),
        CheckConstraint(
            f"code ~ '{_SLUG_CHECK}'",
            name="ck_assessment_methodologies_code",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_methodologies_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_assessment_methodologies_status",
        ),
        CheckConstraint(
            "((status = 'draft' AND published_at IS NULL) OR "
            "(status IN ('published', 'retired') AND published_at IS NOT NULL))",
            name="ck_assessment_methodologies_publication",
        ),
        Index("ix_assessment_methodologies_company_id", "company_id"),
        Index(
            "uq_assessment_methodologies_system_code_version",
            "code",
            "version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND owner_type = 'system'"),
        ),
        Index(
            "uq_assessment_methodologies_company_code_version",
            "company_id",
            "code",
            "version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND owner_type = 'company'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    company_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_editable(self) -> bool:
        """Only drafts are editable; services must create a new draft version."""

        return self.status == "draft" and self.deleted_at is None


class AssessmentTemplate(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "assessment_templates"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('library', 'company')",
            name="ck_assessment_templates_scope",
        ),
        CheckConstraint(
            "((scope = 'library' AND company_id IS NULL) OR "
            "(scope = 'company' AND company_id IS NOT NULL))",
            name="ck_assessment_templates_scope_context",
        ),
        CheckConstraint(
            "source_library_version_id IS NULL OR scope = 'company'",
            name="ck_assessment_templates_source_scope",
        ),
        CheckConstraint(
            f"code ~ '{_SLUG_CHECK}'",
            name="ck_assessment_templates_code",
        ),
        CheckConstraint(
            "activity_type IN ('evaluation', 'measurement', 'walkthrough', "
            "'checklist', 'test', 'survey', 'attestation')",
            name="ck_assessment_templates_activity_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_assessment_templates_status",
        ),
        Index("ix_assessment_templates_company_id", "company_id"),
        Index(
            "ix_assessment_templates_source_library_version_id",
            "source_library_version_id",
        ),
        Index(
            "uq_assessment_templates_active_library_code",
            "code",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status = 'active' AND scope = 'library'"
            ),
        ),
        Index(
            "uq_assessment_templates_active_company_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status = 'active' AND scope = 'company'"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    company_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_library_version_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_template_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class AssessmentTemplateVersion(Base, TimestampMixin):
    __tablename__ = "assessment_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version",
            name="uq_assessment_template_versions_template_version",
        ),
        UniqueConstraint(
            "id",
            "template_id",
            name="uq_assessment_template_versions_id_template",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_assessment_template_versions_version",
        ),
        CheckConstraint(
            "edit_revision >= 1",
            name="ck_assessment_template_versions_edit_revision",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_assessment_template_versions_status",
        ),
        CheckConstraint(
            "((status = 'published' AND published_at IS NOT NULL) OR "
            "(status = 'draft' AND published_at IS NULL) OR status = 'archived')",
            name="ck_assessment_template_versions_publication",
        ),
        Index(
            "ix_assessment_template_versions_template_status",
            "template_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    edit_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    methodology_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_methodologies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    local_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_editable(self) -> bool:
        """Published/archived versions are immutable domain snapshots."""

        return self.status == "draft"


class AssessmentTemplateSection(Base, TimestampMixin):
    __tablename__ = "assessment_template_sections"
    __table_args__ = (
        UniqueConstraint(
            "template_version_id",
            "code",
            name="uq_assessment_template_sections_version_code",
        ),
        UniqueConstraint(
            "id",
            "template_version_id",
            name="uq_assessment_template_sections_id_version",
        ),
        ForeignKeyConstraint(
            ["parent_section_id", "template_version_id"],
            [
                "assessment_template_sections.id",
                "assessment_template_sections.template_version_id",
            ],
            name="fk_assessment_template_sections_parent_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"code ~ '{_SLUG_CHECK}'",
            name="ck_assessment_template_sections_code",
        ),
        CheckConstraint(
            "section_kind IN ('section', 'zone', 'group')",
            name="ck_assessment_template_sections_kind",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_sections_sort_order",
        ),
        CheckConstraint(
            "weight IS NULL OR weight >= 0",
            name="ck_assessment_template_sections_weight",
        ),
        CheckConstraint(
            "parent_section_id IS NULL OR parent_section_id <> id",
            name="ck_assessment_template_sections_not_self_parent",
        ),
        Index(
            "ix_assessment_template_sections_version_sort",
            "template_version_id",
            "sort_order",
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
    parent_section_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)


class AssessmentTemplateItem(Base, TimestampMixin):
    __tablename__ = "assessment_template_items"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "template_version_id",
            name="uq_assessment_template_items_id_version",
        ),
        UniqueConstraint(
            "template_version_id",
            "code",
            name="uq_assessment_template_items_version_code",
        ),
        ForeignKeyConstraint(
            ["section_id", "template_version_id"],
            [
                "assessment_template_sections.id",
                "assessment_template_sections.template_version_id",
            ],
            name="fk_assessment_template_items_section_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"code ~ '{_SLUG_CHECK}'",
            name="ck_assessment_template_items_code",
        ),
        CheckConstraint(
            "response_type IN ('boolean', 'score', 'integer', 'decimal', 'text', "
            "'single_choice', 'multi_choice', 'date', 'time')",
            name="ck_assessment_template_items_response_type",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_items_sort_order",
        ),
        CheckConstraint(
            "weight IS NULL OR weight >= 0",
            name="ck_assessment_template_items_weight",
        ),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_assessment_template_items_value_range",
        ),
        CheckConstraint(
            "passing_value IS NULL OR "
            "((min_value IS NULL OR passing_value >= min_value) AND "
            "(max_value IS NULL OR passing_value <= max_value))",
            name="ck_assessment_template_items_passing_range",
        ),
        CheckConstraint(
            "evidence_mode IN ('none', 'optional_photo', 'required_photo', "
            "'optional_comment', 'required_comment', 'photo_and_comment')",
            name="ck_assessment_template_items_evidence_mode",
        ),
        CheckConstraint(
            "criticality IN ('normal', 'critical', 'stop_factor')",
            name="ck_assessment_template_items_criticality",
        ),
        Index(
            "ix_assessment_template_items_section_sort",
            "section_id",
            "sort_order",
        ),
        Index(
            "ix_assessment_template_items_version_sort",
            "template_version_id",
            "sort_order",
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
    section_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    min_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    max_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    passing_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    evidence_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    criticality: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class AssessmentTemplateItemOption(Base, TimestampMixin):
    __tablename__ = "assessment_template_item_options"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "code",
            name="uq_assessment_template_item_options_item_code",
        ),
        CheckConstraint(
            f"code ~ '{_SLUG_CHECK}'",
            name="ck_assessment_template_item_options_code",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_assessment_template_item_options_sort_order",
        ),
        Index(
            "ix_assessment_template_item_options_item_sort",
            "item_id",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_template_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    numeric_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    is_disqualifying: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
