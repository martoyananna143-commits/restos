"""add_organization_id_to_evaluation_types

Revision ID: add_org_to_eval_types
Revises: remove_eval_type_criteria
Create Date: 2026-01-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_org_to_eval_types'
down_revision = 'remove_eval_type_criteria'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add organization_id column (nullable first for existing data)
    op.add_column(
        'evaluation_types',
        sa.Column('organization_id', sa.Integer(), nullable=True)
    )
    
    # Drop old unique constraints (name and code should be unique per organization, not globally)
    op.drop_constraint('evaluation_types_name_key', 'evaluation_types', type_='unique')
    op.drop_constraint('evaluation_types_code_key', 'evaluation_types', type_='unique')
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_evaluation_types_organization_id',
        'evaluation_types',
        'organizations',
        ['organization_id'],
        ['id'],
        ondelete='CASCADE'
    )
    
    # Add composite unique constraints (unique within organization)
    op.create_unique_constraint(
        'uq_evaluation_types_org_name',
        'evaluation_types',
        ['organization_id', 'name']
    )
    op.create_unique_constraint(
        'uq_evaluation_types_org_code',
        'evaluation_types',
        ['organization_id', 'code']
    )
    
    # Create index for organization_id
    op.create_index(
        'ix_evaluation_types_organization_id',
        'evaluation_types',
        ['organization_id']
    )


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_evaluation_types_organization_id', table_name='evaluation_types')
    
    # Drop composite unique constraints
    op.drop_constraint('uq_evaluation_types_org_code', 'evaluation_types', type_='unique')
    op.drop_constraint('uq_evaluation_types_org_name', 'evaluation_types', type_='unique')
    
    # Drop foreign key
    op.drop_constraint('fk_evaluation_types_organization_id', 'evaluation_types', type_='foreignkey')
    
    # Restore old unique constraints
    op.create_unique_constraint('evaluation_types_code_key', 'evaluation_types', ['code'])
    op.create_unique_constraint('evaluation_types_name_key', 'evaluation_types', ['name'])
    
    # Drop organization_id column
    op.drop_column('evaluation_types', 'organization_id')
