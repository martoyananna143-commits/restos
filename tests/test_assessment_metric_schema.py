"""Schema contracts for versioned restaurant assessment metrics."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.infra.database.models import (
    AssessmentAggregationPolicy,
    AssessmentItemMetricMapping,
    AssessmentMetricDefinition,
    AssessmentMetricObservation,
    AssessmentProductMeasurement,
    AssessmentProductMeasurementItem,
    AssessmentScoringPolicy,
    AssessmentTemplateImportSource,
    AssessmentTemplateItem,
    Base,
)


def test_metric_foundation_tables_are_registered() -> None:
    assert {
        "assessment_metric_definitions",
        "assessment_scoring_policies",
        "assessment_item_metric_mappings",
        "assessment_metric_observations",
        "assessment_aggregation_policies",
        "assessment_template_import_sources",
        "assessment_product_measurements",
        "assessment_product_measurement_items",
    }.issubset(Base.metadata.tables)
    assert len(Base.metadata.tables) == 55


def test_metric_definition_is_versioned_and_has_one_active_code() -> None:
    table = AssessmentMetricDefinition.__table__
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_metric_definitions_code_version"
        for value in table.constraints
    )
    assert {
        value.name for value in table.constraints if isinstance(value, CheckConstraint)
    } == {
        "ck_assessment_metric_definitions_code",
        "ck_assessment_metric_definitions_version",
        "ck_assessment_metric_definitions_status",
    }


def test_scoring_and_mapping_are_owned_by_template_version() -> None:
    scoring = AssessmentScoringPolicy.__table__
    mapping = AssessmentItemMetricMapping.__table__
    assert list(scoring.primary_key.columns.keys()) == ["template_version_id"]
    assert any(
        value.name == "fk_assessment_item_metric_mappings_item_version"
        for value in mapping.foreign_key_constraints
    )
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_item_metric_mappings_item_metric"
        for value in mapping.constraints
    )
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_template_items_id_version"
        for value in AssessmentTemplateItem.__table__.constraints
    )
    assert mapping.c.contribution_weight.nullable is True


def test_observation_is_idempotent_and_contains_no_answers_or_pii() -> None:
    table = AssessmentMetricObservation.__table__
    assert {value.name for value in table.indexes if value.unique} == {
        "uq_assessment_metric_observations_attempt_metric",
        "uq_assessment_metric_observations_product_metric",
    }
    forbidden = {
        "answer",
        "answers",
        "comment",
        "phone",
        "name",
        "token",
        "credential",
    }
    assert forbidden.isdisjoint(table.columns.keys())
    assert table.c.critical_failure_count.nullable is False
    assert table.c.stop_factor_count.nullable is False


def test_repeatable_product_measurement_is_normalized_and_venue_scoped() -> None:
    measurement = AssessmentProductMeasurement.__table__
    item = AssessmentProductMeasurementItem.__table__
    assert any(
        value.name == "fk_assessment_product_measurements_venue_company"
        for value in measurement.foreign_key_constraints
    )
    assert "position_name" in item.columns
    assert "measurement_id" in item.columns
    assert "phone" not in item.columns


def test_policy_and_provenance_are_bounded_and_versioned() -> None:
    policy = AssessmentAggregationPolicy.__table__
    source = AssessmentTemplateImportSource.__table__
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_aggregation_policies_company_metric_version"
        for value in policy.constraints
    )
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_template_import_sources_version_sha"
        for value in source.constraints
    )
    assert {
        "source_filename",
        "source_sha256",
        "manifest_sha256",
        "provenance",
    }.issubset(source.columns.keys())
