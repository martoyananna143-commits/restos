"""add google sheet source fields to criterion_sets

Revision ID: add_google_sheet_source
Revises: drop_check_diff_emp
Create Date: 2026-05-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "add_google_sheet_source"
down_revision = "drop_check_diff_emp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "criterion_sets",
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default="internal",
        ),
    )
    op.add_column(
        "criterion_sets",
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "criterion_sets",
        sa.Column(
            "source_meta",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("criterion_sets", "source_meta")
    op.drop_column("criterion_sets", "source_url")
    op.drop_column("criterion_sets", "source_type")
