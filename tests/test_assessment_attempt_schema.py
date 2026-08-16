"""Schema contract tests for assigned assessment attempts."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
    Base,
)


def test_assessment_attempt_tables_are_registered():
    assert {
        "assessment_assignments",
        "assessment_attempts",
        "assessment_attempt_answers",
    }.issubset(Base.metadata.tables)
    assert len(Base.metadata.tables) == 55


def test_assignment_schema_has_safe_foreign_keys_and_state_checks():
    table = AssessmentAssignment.__table__
    assert {fk.ondelete for fk in table.foreign_key_constraints} == {
        "RESTRICT",
        "SET NULL",
    }
    checks = {
        value.name for value in table.constraints if isinstance(value, CheckConstraint)
    }
    assert checks == {
        "ck_assessment_assignments_status",
        "ck_assessment_assignments_due_after_assigned",
        "ck_assessment_assignments_state_timestamps",
        "ck_assessment_assignments_purpose",
        "ck_assessment_assignments_operational_venue",
    }


def test_attempt_and_answer_invariants():
    attempt = AssessmentAttempt.__table__
    answer = AssessmentAttemptAnswer.__table__
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_attempts_assignment_id"
        for value in attempt.constraints
    )
    assert any(
        isinstance(value, UniqueConstraint)
        and value.name == "uq_assessment_attempt_answers_attempt_item"
        for value in answer.constraints
    )
    forbidden = {
        "token",
        "secret",
        "credential",
        "private_key",
        "score",
        "passing_value",
    }
    assert forbidden.isdisjoint(attempt.columns.keys())
    assert forbidden.isdisjoint(answer.columns.keys())


def test_revision_and_json_defaults_are_server_controlled():
    attempt = AssessmentAttempt.__table__
    assert str(attempt.c.revision.server_default.arg) == "0"
    assert attempt.c.result_json.nullable is not False
    assert attempt.c.assignment_id.unique is None
