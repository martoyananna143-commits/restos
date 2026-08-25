"""Schema contract for bounded Employee Invitation SMS delivery state."""

from sqlalchemy import CheckConstraint, Index

from app.infra.database.models import Invitation


def test_invitation_delivery_columns_are_minimal_and_non_sensitive():
    table = Invitation.__table__
    status = table.c.delivery_status
    attempts = table.c.delivery_attempt_count
    assert status.nullable is False and status.server_default.arg == "unknown"
    assert attempts.nullable is False and attempts.server_default.arg == "0"
    assert table.c.delivery_attempted_at.nullable is True
    assert table.c.delivery_sent_at.nullable is True
    serialized = " ".join(table.columns.keys()).lower()
    for forbidden in ("plaintext", "delivery_code", "sms_body", "provider_response"):
        assert forbidden not in serialized


def test_invitation_delivery_constraints_are_exact():
    constraints = {
        value.name: str(value.sqltext)
        for value in Invitation.__table__.constraints
        if isinstance(value, CheckConstraint) and value.name
    }
    assert constraints["ck_invitations_delivery_status"] == (
        "delivery_status IN ('delivery_pending', 'sent', 'unknown', 'failed')"
    )
    assert constraints["ck_invitations_delivery_attempt_count"] == (
        "delivery_attempt_count >= 0"
    )
    assert constraints["ck_invitations_delivery_attempted_state"] == (
        "delivery_attempt_count = 0 OR delivery_attempted_at IS NOT NULL"
    )
    assert constraints["ck_invitations_delivery_sent_state"] == (
        "((delivery_status = 'sent' AND delivery_sent_at IS NOT NULL) OR "
        "(delivery_status <> 'sent' AND delivery_sent_at IS NULL))"
    )


def test_invitation_delivery_index_is_scoped_and_non_unique():
    index = next(
        value
        for value in Invitation.__table__.indexes
        if value.name == "ix_invitations_company_delivery"
    )
    assert isinstance(index, Index)
    assert index.unique is False
    assert [column.name for column in index.columns] == [
        "company_id",
        "delivery_status",
    ]
