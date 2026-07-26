"""Add optimistic edit revision to assessment template drafts."""

from alembic import op
import sqlalchemy as sa


revision = "add_assessment_draft_rev"
down_revision = "add_assessment_templates_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_template_versions",
        sa.Column(
            "edit_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_check_constraint(
        "ck_assessment_template_versions_edit_revision",
        "assessment_template_versions",
        "edit_revision >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_assessment_template_versions_edit_revision",
        "assessment_template_versions",
        type_="check",
    )
    op.drop_column("assessment_template_versions", "edit_revision")
