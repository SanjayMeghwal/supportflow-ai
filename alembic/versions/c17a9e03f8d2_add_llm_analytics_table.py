"""add_llm_analytics_table

Revision ID: c17a9e03f8d2
Revises: 8efbad059e12
Create Date: 2026-09-30 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c17a9e03f8d2'
down_revision: Union[str, Sequence[str], None] = '8efbad059e12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add llm_analytics table."""
    op.create_table(
        'llm_analytics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False, server_default='groq'),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('operation', sa.String(length=64), nullable=False, server_default='rag_synthesis'),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('is_estimated', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('error_type', sa.String(length=64), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_llm_analytics_request_id'), 'llm_analytics', ['request_id'], unique=False)
    op.create_index(op.f('ix_llm_analytics_model'), 'llm_analytics', ['model'], unique=False)
    op.create_index(op.f('ix_llm_analytics_operation'), 'llm_analytics', ['operation'], unique=False)
    op.create_index(op.f('ix_llm_analytics_success'), 'llm_analytics', ['success'], unique=False)
    op.create_index(op.f('ix_llm_analytics_created_at'), 'llm_analytics', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_llm_analytics_created_at'), table_name='llm_analytics')
    op.drop_index(op.f('ix_llm_analytics_success'), table_name='llm_analytics')
    op.drop_index(op.f('ix_llm_analytics_operation'), table_name='llm_analytics')
    op.drop_index(op.f('ix_llm_analytics_model'), table_name='llm_analytics')
    op.drop_index(op.f('ix_llm_analytics_request_id'), table_name='llm_analytics')
    op.drop_table('llm_analytics')
