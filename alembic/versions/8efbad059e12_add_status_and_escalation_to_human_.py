"""add_status_and_escalation_to_human_reviews

Revision ID: 8efbad059e12
Revises: a3f8c2d1e9b7
Create Date: 2026-09-25 16:08:32.984294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8efbad059e12'
down_revision: Union[str, Sequence[str], None] = 'a3f8c2d1e9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

review_status_enum = postgresql.ENUM(
    'PENDING', 'APPROVED', 'EDITED', 'REJECTED', 'ESCALATED',
    name='review_status_enum'
)
review_action_enum = postgresql.ENUM(
    'APPROVED', 'EDITED', 'REJECTED', 'ESCALATED',
    name='review_action_enum'
)


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create review_status_enum in postgres
    review_status_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add status, escalation_reason, and resolved_at columns
    op.add_column(
        'human_reviews',
        sa.Column('status', review_status_enum, nullable=False, server_default='PENDING')
    )
    op.add_column(
        'human_reviews',
        sa.Column('escalation_reason', sa.String(length=255), nullable=False, server_default='AI escalation')
    )
    op.add_column(
        'human_reviews',
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 3. Create index on status
    op.create_index(op.f('ix_human_reviews_status'), 'human_reviews', ['status'], unique=False)

    # 4. Make reviewer_id and action_taken nullable for pending reviews
    op.alter_column('human_reviews', 'reviewer_id', existing_type=sa.UUID(), nullable=True)
    op.alter_column('human_reviews', 'action_taken', existing_type=review_action_enum, nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('human_reviews', 'action_taken', existing_type=review_action_enum, nullable=False)
    op.alter_column('human_reviews', 'reviewer_id', existing_type=sa.UUID(), nullable=False)
    op.drop_index(op.f('ix_human_reviews_status'), table_name='human_reviews')
    op.drop_column('human_reviews', 'resolved_at')
    op.drop_column('human_reviews', 'escalation_reason')
    op.drop_column('human_reviews', 'status')
    review_status_enum.drop(op.get_bind(), checkfirst=True)
