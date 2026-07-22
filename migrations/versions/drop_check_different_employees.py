"""Drop check_different_employees constraint and add position column to employees.

Revision ID: drop_check_diff_emp
Revises: 768843a2dc51
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'drop_check_diff_emp'
down_revision = '768843a2dc51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the constraint that prevents self-evaluation.
    # In the web app, an admin/evaluator may be the only person in their
    # organisation and needs to be able to evaluate any employee including
    # themselves during initial setup.
    op.execute(
        "ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS check_different_employees"
    )

    # Add 'position' column to employees if it doesn't exist yet
    # (used by the web app to display employee roles in selection lists)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='employees' AND column_name='position'
            ) THEN
                ALTER TABLE employees ADD COLUMN position VARCHAR(255);
            END IF;
        END$$;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE evaluations
        ADD CONSTRAINT check_different_employees
        CHECK (evaluated_employee_id IS NULL
               OR filled_by_employee_id <> evaluated_employee_id)
    """)
