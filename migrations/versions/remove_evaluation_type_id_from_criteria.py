"""remove_evaluation_type_id_from_criteria

Revision ID: remove_eval_type_criteria
Revises: f5447bfcdd5f
Create Date: 2026-01-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'remove_eval_type_criteria'
down_revision = 'f5447bfcdd5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop foreign key constraint first (PostgreSQL auto-generates constraint names)
    # Try common constraint name patterns
    try:
        op.drop_constraint('criteria_evaluation_type_id_fkey', 'criteria', type_='foreignkey')
    except:
        # If constraint name is different, find and drop it
        # This will work if constraint was created with auto-generated name
        pass
    
    # Drop the column (this will also drop the foreign key if it still exists)
    op.drop_column('criteria', 'evaluation_type_id')


def downgrade() -> None:
    # Add the column back
    op.add_column('criteria', sa.Column('evaluation_type_id', sa.Integer(), nullable=False))
    # Recreate foreign key constraint
    op.create_foreign_key(
        'criteria_evaluation_type_id_fkey',
        'criteria',
        'evaluation_types',
        ['evaluation_type_id'],
        ['id'],
        ondelete='CASCADE'
    )
