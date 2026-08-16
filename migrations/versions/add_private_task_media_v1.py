"""Add retry-safe private task-media deletion state.

Revision ID: add_private_task_media_v1
Revises: add_organization_workflows_v1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "add_private_task_media_v1"
down_revision: str | None = "add_organization_workflows_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_task_photos_status", "task_photos", type_="check")
    op.create_check_constraint(
        "ck_task_photos_status",
        "task_photos",
        "media_status IN ('pending','ready','deleting','deleted')",
    )


def downgrade() -> None:
    deleting_count = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM task_photos WHERE media_status = 'deleting'")
        )
        .scalar_one()
    )
    if deleting_count:
        raise RuntimeError(
            "cannot downgrade private task media while deletions are in progress"
        )
    op.drop_constraint("ck_task_photos_status", "task_photos", type_="check")
    op.create_check_constraint(
        "ck_task_photos_status",
        "task_photos",
        "media_status IN ('pending','ready','deleted')",
    )
