"""add_hnsw_index_to_document_chunks

Revision ID: 5ee5002338bc
Revises: f85a06401df1
Create Date: 2026-09-24 11:00:26.441242

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = '5ee5002338bc'
down_revision: Union[str, Sequence[str], None] = 'f85a06401df1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create HNSW vector index on document_chunks.embedding using vector_cosine_ops."""
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops);
        """
    )


def downgrade() -> None:
    """Drop HNSW vector index on document_chunks.embedding."""
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")
