"""Add value_type to criteria and support multiple value types in criterion_values

Revision ID: add_criterion_value_types
Revises: 
Create Date: 2024-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_criterion_value_types'
down_revision = '277eb272246b'  # Последняя миграция: add_criterion_set_id_to_evaluations
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле value_type в таблицу criteria
    op.add_column('criteria', sa.Column('value_type', sa.String(20), nullable=False, server_default='boolean'))
    
    # Изменяем таблицу criterion_values для поддержки разных типов значений
    # Сначала делаем поле value nullable для обратной совместимости
    op.alter_column('criterion_values', 'value', nullable=True)
    
    # Добавляем JSONB поле для хранения значений разных типов
    op.add_column('criterion_values', sa.Column('value_json', postgresql.JSONB, nullable=True))
    
    # Мигрируем существующие boolean значения в JSONB
    op.execute("""
        UPDATE criterion_values
        SET value_json = jsonb_build_object('type', 'boolean', 'value', value::text)
        WHERE value_json IS NULL AND value IS NOT NULL
    """)
    
    # Для записей без значения устанавливаем дефолтное значение
    op.execute("""
        UPDATE criterion_values
        SET value_json = jsonb_build_object('type', 'boolean', 'value', 'false')
        WHERE value_json IS NULL
    """)
    
    # Делаем value_json NOT NULL после миграции данных
    # Используем server_default для новых записей
    op.alter_column('criterion_values', 'value_json', nullable=False, server_default='{"type": "boolean", "value": false}')


def downgrade() -> None:
    # Восстанавливаем старое поле value из JSONB
    op.execute("""
        UPDATE criterion_values
        SET value = (value_json->>'value')::boolean
        WHERE value_json->>'type' = 'boolean'
    """)
    
    # Восстанавливаем NOT NULL для value
    op.alter_column('criterion_values', 'value', nullable=False)
    
    # Удаляем новые поля
    op.drop_column('criterion_values', 'value_json')
    op.drop_column('criteria', 'value_type')

