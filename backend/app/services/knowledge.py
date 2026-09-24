"""Knowledge base service for document ingestion, deduplication, and lifecycle management."""

import hashlib
from typing import Any
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument, SourceType
from backend.app.services.chunking import RecursiveTextChunker
from backend.app.services.extractors import ExtractionError, detect_source_type, extract_text


class DuplicateDocumentError(Exception):
    """Raised when an identical document (matching SHA-256 checksum) already exists."""

    def __init__(self, existing_document_id: uuid.UUID, checksum: str) -> None:
        self.existing_document_id = existing_document_id
        self.checksum = checksum
        super().__init__(
            f"Document with checksum '{checksum}' already exists (ID: {existing_document_id})."
        )


class KnowledgeService:
    """Orchestrates knowledge document ingestion, deduplication, and persistence."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self.chunker = RecursiveTextChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def ingest_document(
        self,
        db: AsyncSession,
        *,
        title: str,
        content_bytes: bytes,
        filename: str,
        source_type: SourceType | None = None,
        source_uri: str | None = None,
    ) -> KnowledgeDocument:
        """Ingest, extract, chunk, and persist a knowledge document.

        Guarantees:
          1. Computes SHA-256 checksum from raw bytes.
          2. Enforces deduplication: raises DuplicateDocumentError if checksum already exists.
          3. Extracts text using source-specific extractor.
          4. Chunks text using RecursiveTextChunker.
          5. Stores KnowledgeDocument and DocumentChunks atomically.
        """
        # 1. Compute SHA-256 checksum
        checksum = hashlib.sha256(content_bytes).hexdigest()

        # 2. Check for duplicate checksum
        existing_result = await db.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.checksum_sha256 == checksum
            )
        )
        existing_id = existing_result.scalar_one_or_none()
        if existing_id is not None:
            raise DuplicateDocumentError(existing_id, checksum)

        # 3. Detect source type if not specified
        resolved_source_type = detect_source_type(filename, source_type)

        # 4. Extract text and structural metadata
        extracted_text, doc_metadata = extract_text(
            content_bytes=content_bytes,
            source_type=resolved_source_type,
            filename=filename,
        )

        # 5. Chunk extracted text
        merged_metadata: dict[str, Any] = {
            **doc_metadata,
            "title": title,
            "source_type": resolved_source_type.value,
        }
        if source_uri:
            merged_metadata["source_uri"] = source_uri

        chunks = self.chunker.split_text(extracted_text, merged_metadata)
        if not chunks:
            raise ExtractionError("Document produced 0 text chunks after processing.")

        # 6. Atomic database persistence
        document = KnowledgeDocument(
            title=title,
            source_type=resolved_source_type,
            source_uri=source_uri,
            checksum_sha256=checksum,
            is_active=True,
        )
        db.add(document)
        await db.flush()

        db_chunks = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.text,
                metadata_json=chunk.metadata,
                embedding=None,  # Embeddings populated in Phase 7
            )
            for chunk in chunks
        ]
        db.add_all(db_chunks)

        await db.commit()
        await db.refresh(document)

        return document

    async def list_documents(
        self,
        db: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 20,
        source_type: SourceType | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[tuple[KnowledgeDocument, int]], int]:
        """List documents with pagination, filters, and chunk counts."""
        # Query total count
        count_query = select(func.count(KnowledgeDocument.id))
        if source_type is not None:
            count_query = count_query.where(KnowledgeDocument.source_type == source_type)
        if is_active is not None:
            count_query = count_query.where(KnowledgeDocument.is_active == is_active)

        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        # Query documents with chunk count via subquery/join
        chunk_count_subquery = (
            select(
                DocumentChunk.document_id,
                func.count(DocumentChunk.id).label("chunk_count"),
            )
            .group_by(DocumentChunk.document_id)
            .subquery()
        )

        doc_query = (
            select(
                KnowledgeDocument,
                func.coalesce(chunk_count_subquery.c.chunk_count, 0).label("chunk_count"),
            )
            .outerjoin(
                chunk_count_subquery,
                KnowledgeDocument.id == chunk_count_subquery.c.document_id,
            )
            .order_by(KnowledgeDocument.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        if source_type is not None:
            doc_query = doc_query.where(KnowledgeDocument.source_type == source_type)
        if is_active is not None:
            doc_query = doc_query.where(KnowledgeDocument.is_active == is_active)

        result = await db.execute(doc_query)
        items = [(row[0], int(row[1])) for row in result.all()]

        return items, total

    async def get_document_detail(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> KnowledgeDocument | None:
        """Fetch a document along with all its chunks ordered by chunk_index."""
        query = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .options(selectinload(KnowledgeDocument.chunks))
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def delete_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> bool:
        """Delete a document and cascade-delete its chunks."""
        query = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        result = await db.execute(query)
        doc = result.scalar_one_or_none()
        if doc is None:
            return False

        await db.delete(doc)
        await db.commit()
        return True
