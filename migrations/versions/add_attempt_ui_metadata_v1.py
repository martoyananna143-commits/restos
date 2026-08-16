"""Persist non-scoring attempt UI metadata.

Revision ID: add_attempt_ui_metadata_v1
Revises: add_account_invite_join_v1
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_attempt_ui_metadata_v1"
down_revision: Union[str, None] = "add_account_invite_join_v1"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "assessment_attempts",
        sa.Column(
            "ui_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("assessment_attempts", "ui_metadata_json")
