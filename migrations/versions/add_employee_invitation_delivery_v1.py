"""Persist safe Employee Invitation SMS delivery outcomes.

Revision ID: employee_invite_delivery_v1
Revises: add_assessment_history_cursor_v1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "employee_invite_delivery_v1"
down_revision: str | None = "add_assessment_history_cursor_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column(
            "delivery_status",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "delivery_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "invitations",
        sa.Column("delivery_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("delivery_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_invitations_delivery_status",
        "invitations",
        "delivery_status IN ('delivery_pending', 'sent', 'unknown', 'failed')",
    )
    op.create_check_constraint(
        "ck_invitations_delivery_attempt_count",
        "invitations",
        "delivery_attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_invitations_delivery_attempted_state",
        "invitations",
        "delivery_attempt_count = 0 OR delivery_attempted_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_invitations_delivery_sent_state",
        "invitations",
        "((delivery_status = 'sent' AND delivery_sent_at IS NOT NULL) OR "
        "(delivery_status <> 'sent' AND delivery_sent_at IS NULL))",
    )
    op.create_index(
        "ix_invitations_company_delivery",
        "invitations",
        ["company_id", "delivery_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_company_delivery", table_name="invitations")
    op.drop_constraint(
        "ck_invitations_delivery_sent_state", "invitations", type_="check"
    )
    op.drop_constraint(
        "ck_invitations_delivery_attempted_state", "invitations", type_="check"
    )
    op.drop_constraint(
        "ck_invitations_delivery_attempt_count", "invitations", type_="check"
    )
    op.drop_constraint(
        "ck_invitations_delivery_status", "invitations", type_="check"
    )
    op.drop_column("invitations", "delivery_sent_at")
    op.drop_column("invitations", "delivery_attempted_at")
    op.drop_column("invitations", "delivery_attempt_count")
    op.drop_column("invitations", "delivery_status")
