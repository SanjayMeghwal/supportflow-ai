"""add_fts_gin_index_to_document_chunks

Adds a PostgreSQL GIN expression index on to_tsvector('english', chunk_text)
for Phase 8 Full-Text Search retrieval over knowledge document chunks.

Design notes
------------
* An *expression* GIN index is used rather than a stored tsvector column.
  - No SQLAlchemy model change required.
  - PostgreSQL automatically maintains the index when chunk_text is written.
  - Since document chunks are immutable after ingestion (write-once), there
    is no risk of stale tsvector values.
* The 'english' text-search configuration provides stemming and stopword
  removal appropriate for the customer-support domain.
* The IF NOT EXISTS guard makes the migration idempotent and safe to replay
  on partially-migrated environments.

Revision ID: a3f8c2d1e9b7
Revises: 5ee5002338bc
Create Date: 2026-09-24 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = 'a3f8c2d1e9b7'
down_revision: Union[str, Sequence[str], None] = '5ee5002338bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create GIN expression index for PostgreSQL Full-Text Search on chunk_text.

    The index is functionally equivalent to a stored tsvector column but
    requires no schema-level column addition.  PostgreSQL evaluates
    to_tsvector('english', chunk_text) at index-build time and stores the
    resulting lexeme set in the GIN structure.  Subsequent FTS queries that
    reference the same expression will transparently use this index.
    """
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_chunk_text_fts
        ON document_chunks
        USING gin (to_tsvector('english', chunk_text));
        """
    )


def downgrade() -> None:
    """Drop GIN Full-Text Search index from document_chunks."""
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_chunk_text_fts;"
    )
