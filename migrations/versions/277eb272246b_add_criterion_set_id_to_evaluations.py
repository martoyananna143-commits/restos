"""add_criterion_set_id_to_evaluations

Revision ID: 277eb272246b
Revises: add_criterion_sets
Create Date: 2025-12-19 02:39:40.682331

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '277eb272246b'
down_revision = 'add_criterion_sets'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле criterion_set_id в таблицу evaluations
    op.add_column(
        'evaluations',
        sa.Column('criterion_set_id', sa.Integer(), nullable=True)
    )
    
    # Создаем внешний ключ
    op.create_foreign_key(
        'fk_evaluations_criterion_set_id',
        'evaluations',
        'criterion_sets',
        ['criterion_set_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Удаляем внешний ключ
    op.drop_constraint('fk_evaluations_criterion_set_id', 'evaluations', type_='foreignkey')
    
    # Удаляем колонку
    op.drop_column('evaluations', 'criterion_set_id')
