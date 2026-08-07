"""Schema contract tests for Account assessment management."""

from sqlalchemy import Index

from app.infra.database.models import AssessmentAssignment, Base


def test_management_reuses_existing_assignment_table():
    assert len(Base.metadata.tables) == 39
    assert "assessment_assignments" in Base.metadata.tables


def test_assigner_account_fk_is_nullable_and_set_null():
    column = AssessmentAssignment.__table__.c.assigned_by_account_id
    assert column.nullable is True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.target_fullname == "accounts.id"
    assert foreign_key.ondelete == "SET NULL"


def test_active_assignment_partial_unique_index_is_exact():
    index = next(
        value
        for value in AssessmentAssignment.__table__.indexes
        if value.name == "uq_assessment_assignments_active_employee_version"
    )
    assert isinstance(index, Index)
    assert index.unique is True
    assert [column.name for column in index.columns] == [
        "company_id",
        "employee_profile_id",
        "template_version_id",
    ]
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "status IN ('assigned', 'in_progress')"
    )


def test_management_schema_adds_no_sensitive_columns():
    serialized = " ".join(AssessmentAssignment.__table__.columns.keys()).lower()
    for forbidden in (
        "answer",
        "token",
        "cookie",
        "credential",
        "private_key",
        "numeric_score",
        "passing_value",
    ):
        assert forbidden not in serialized
