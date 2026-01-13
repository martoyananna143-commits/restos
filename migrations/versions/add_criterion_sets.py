"""add_criterion_sets

Revision ID: add_criterion_sets
Revises: f5447bfcdd5f
Create Date: 2025-12-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_criterion_sets'
down_revision = 'f5447bfcdd5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу criterion_sets
    op.create_table(
        'criterion_sets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'name', name='uq_organization_criterion_set_name')
    )
    
    # Создаем промежуточную таблицу для связи many-to-many
    op.create_table(
        'criterion_set_criterion',
        sa.Column('criterion_set_id', sa.Integer(), nullable=False),
        sa.Column('criterion_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['criterion_set_id'], ['criterion_sets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['criterion_id'], ['criteria.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('criterion_set_id', 'criterion_id')
    )


def downgrade() -> None:
    op.drop_table('criterion_set_criterion')
    op.drop_table('criterion_sets')

