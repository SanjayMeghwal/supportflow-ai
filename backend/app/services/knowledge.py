"""Knowledge base service for document ingestion, deduplication, and lifecycle management."""

import hashlib
from typing import Any
import uuid
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument, SourceType
from backend.app.services.chunking import RecursiveTextChunker
from backend.app.services.embedding import EmbeddingService, get_embedding_service
from backend.app.services.extractors import ExtractionError, detect_source_type, extract_text
from backend.app.services.ranking import RankedCandidate, reciprocal_rank_fusion
from backend.app.services.reranker import RerankerService, get_reranker_service

# ---------------------------------------------------------------------------
# Candidate pool constants for hybrid retrieval and cross-encoder reranking
# ---------------------------------------------------------------------------

#: Multiplier applied to top_k to form the candidate pool retrieved from each
#: retrieval system before RRF fusion.  A value of 4 means that for a request
#: of top_k=5, each system fetches up to 20 candidates.  This ensures that
#: documents appearing at moderate ranks in one system still have a chance to
#: surface in the final fused list.
_CANDIDATE_MULTIPLIER: int = 4

#: Hard upper bound on candidates fetched per retrieval system, regardless of
#: top_k.  Prevents unbounded database result sets on large top_k values.
_MAX_CANDIDATES_PER_SYSTEM: int = 100

#: Multiplier applied to top_k to form the candidate pool retrieved from
#: hybrid search before cross-encoder reranking.
_RERANK_CANDIDATE_MULTIPLIER: int = 4

#: Hard upper bound on candidates passed to the cross-encoder reranker.
#: Bounds computationally intensive joint self-attention inference.
_MAX_RERANK_CANDIDATES: int = 50


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
        embedding_service: EmbeddingService | None = None,
        reranker_service: RerankerService | None = None,
    ) -> None:
        self.chunker = RecursiveTextChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.embedding_service = embedding_service or get_embedding_service()
        self.reranker_service = reranker_service or get_reranker_service()

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

        # 6. Generate vector embeddings for all chunks in batch
        chunk_texts = [chunk.text for chunk in chunks]
        embeddings = self.embedding_service.embed_batch(chunk_texts)

        # 7. Atomic database persistence
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
                embedding=embeddings[i],
            )
            for i, chunk in enumerate(chunks)
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

    async def search_similar_chunks(
        self,
        db: AsyncSession,
        *,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Perform semantic similarity search on knowledge chunks using pgvector cosine distance.

        1. Generates query embedding using local embedding service.
        2. Computes cosine distance via DocumentChunk.embedding.cosine_distance(query_vector).
        3. Joins KnowledgeDocument to filter active documents.
        4. Calculates similarity score = 1.0 - distance.
        5. Orders by distance ascending (most similar first) and limits to top_k.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        query_embedding = self.embedding_service.embed_text(query.strip())

        distance_expr = DocumentChunk.embedding.cosine_distance(query_embedding)
        score_expr = (1.0 - distance_expr).label("similarity_score")

        stmt = (
            select(
                DocumentChunk,
                KnowledgeDocument.title.label("document_title"),
                score_expr,
            )
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.is_active == True,
                DocumentChunk.embedding.isnot(None),
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )

        result = await db.execute(stmt)
        rows = result.all()

        search_results: list[dict[str, Any]] = []
        for chunk, doc_title, score in rows:
            similarity = round(float(score), 4) if score is not None else 0.0
            search_results.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": doc_title,
                "chunk_index": chunk.chunk_index,
                "content": chunk.chunk_text,
                "score": similarity,
                "metadata": chunk.metadata_json or {},
            })

        return search_results

    async def search_full_text(
        self,
        db: AsyncSession,
        *,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Perform PostgreSQL Full-Text Search over knowledge chunk text.

        Uses websearch_to_tsquery for natural-language query parsing:
        - Handles multi-word queries without operator syntax.
        - Gracefully degrades on stopword-only queries (returns empty list).
        - Supports quoted phrases and implicit AND between words.

        Only chunks belonging to active KnowledgeDocuments are searched.
        ts_rank is computed entirely inside PostgreSQL using the GIN index.

        Returns
        -------
        list[dict]
            Up to ``top_k`` results ordered by descending FTS rank.
            Each result contains: chunk_id, document_id, document_title,
            chunk_index, content, score (ts_rank float), metadata.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        cleaned_query = query.strip()

        stmt = text(
            """
            SELECT
                dc.id            AS chunk_id,
                dc.document_id,
                kd.title         AS document_title,
                dc.chunk_index,
                dc.chunk_text,
                dc.metadata_json,
                ts_rank(
                    to_tsvector('english', dc.chunk_text),
                    websearch_to_tsquery('english', :query)
                )                AS fts_rank
            FROM document_chunks dc
            JOIN knowledge_documents kd
                ON dc.document_id = kd.id
            WHERE
                kd.is_active = TRUE
                AND to_tsvector('english', dc.chunk_text)
                    @@ websearch_to_tsquery('english', :query)
            ORDER BY fts_rank DESC
            LIMIT :limit
            """
        )

        result = await db.execute(stmt, {"query": cleaned_query, "limit": top_k})
        rows = result.mappings().all()

        return [
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "document_title": row["document_title"],
                "chunk_index": row["chunk_index"],
                "content": row["chunk_text"],
                "score": round(float(row["fts_rank"]), 6),
                "metadata": dict(row["metadata_json"]) if row["metadata_json"] else {},
            }
            for row in rows
        ]

    async def search_hybrid(
        self,
        db: AsyncSession,
        *,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Perform hybrid search combining dense vector and PostgreSQL FTS via RRF.

        Retrieval strategy
        ------------------
        1. Compute a candidate pool from each system independently:
           - Vector candidates = min(top_k * 4, 100)
           - FTS candidates   = min(top_k * 4, 100)
        2. Both systems search over identical authorized document space
           (active documents only).
        3. Fuse ranked candidate lists using Reciprocal Rank Fusion (k=60).
        4. Return the top-k fused results ordered by descending RRF score.

        The candidate multiplier ensures that documents with moderate ranks
        in one system but high ranks in the other can still surface in the
        final top-k.  Using a bounded pool prevents excessive DB result sets.

        Returns
        -------
        list[dict]
            Up to ``top_k`` results.  Each result exposes:
            chunk_id, document_id, document_title, chunk_index, content,
            score (rrf_score), vector_rank, fts_rank, metadata.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        candidate_limit = min(top_k * _CANDIDATE_MULTIPLIER, _MAX_CANDIDATES_PER_SYSTEM)

        # 1. Vector candidate retrieval
        query_embedding = self.embedding_service.embed_text(query.strip())

        distance_expr = DocumentChunk.embedding.cosine_distance(query_embedding)

        vec_stmt = (
            select(
                DocumentChunk,
                KnowledgeDocument.title.label("document_title"),
            )
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.is_active == True,  # noqa: E712
                DocumentChunk.embedding.isnot(None),
            )
            .order_by(distance_expr.asc())
            .limit(candidate_limit)
        )

        vec_result = await db.execute(vec_stmt)
        vec_rows = vec_result.all()

        vector_candidates: list[RankedCandidate] = [
            RankedCandidate(
                chunk_id=str(chunk.id),
                rank=rank + 1,
                document_id=str(chunk.document_id),
                document_title=doc_title,
                chunk_index=chunk.chunk_index,
                content=chunk.chunk_text,
                metadata=chunk.metadata_json or {},
            )
            for rank, (chunk, doc_title) in enumerate(vec_rows)
        ]

        # 2. FTS candidate retrieval
        fts_stmt = text(
            """
            SELECT
                dc.id            AS chunk_id,
                dc.document_id,
                kd.title         AS document_title,
                dc.chunk_index,
                dc.chunk_text,
                dc.metadata_json
            FROM document_chunks dc
            JOIN knowledge_documents kd
                ON dc.document_id = kd.id
            WHERE
                kd.is_active = TRUE
                AND to_tsvector('english', dc.chunk_text)
                    @@ websearch_to_tsquery('english', :query)
            ORDER BY
                ts_rank(
                    to_tsvector('english', dc.chunk_text),
                    websearch_to_tsquery('english', :query)
                ) DESC
            LIMIT :limit
            """
        )

        fts_result = await db.execute(
            fts_stmt, {"query": query.strip(), "limit": candidate_limit}
        )
        fts_rows = fts_result.mappings().all()

        fts_candidates: list[RankedCandidate] = [
            RankedCandidate(
                chunk_id=str(row["chunk_id"]),
                rank=rank + 1,
                document_id=str(row["document_id"]),
                document_title=row["document_title"],
                chunk_index=row["chunk_index"],
                content=row["chunk_text"],
                metadata=dict(row["metadata_json"]) if row["metadata_json"] else {},
            )
            for rank, row in enumerate(fts_rows)
        ]

        # 3. RRF fusion
        fused = reciprocal_rank_fusion(
            vector_candidates,
            fts_candidates,
            top_k=top_k,
        )

        # 4. Assemble final result dicts
        return [
            {
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "document_title": r.document_title,
                "chunk_index": r.chunk_index,
                "content": r.content,
                "score": r.rrf_score,
                "vector_rank": r.vector_rank,
                "fts_rank": r.fts_rank,
                "metadata": r.metadata,
            }
            for r in fused
        ]

    async def search_reranked(
        self,
        db: AsyncSession,
        *,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Perform hybrid search followed by local cross-encoder reranking.

        Two-stage retrieval pipeline:
        1. Retrieval stage: Hybrid search (vector + FTS via RRF) fetches a bounded
           candidate pool: min(top_k * 4, 50).
        2. Reranking stage: The local Cross-Encoder (ms-marco-MiniLM-L-6-v2) scores
           each (query, chunk_content) pair via full cross-attention.
        3. Returns top_k results ordered by cross-encoder relevance score, preserving
           vector_rank, fts_rank, and rrf_score metadata.

        Returns
        -------
        list[dict]
            Up to ``top_k`` results. Each result exposes:
            chunk_id, document_id, document_title, chunk_index, content,
            score (rerank_score), rerank_score, rrf_score, vector_rank, fts_rank, metadata.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        candidate_limit = min(top_k * _RERANK_CANDIDATE_MULTIPLIER, _MAX_RERANK_CANDIDATES)

        # 1. Retrieve hybrid candidates up to candidate_limit
        hybrid_candidates = await self.search_hybrid(
            db=db,
            query=query.strip(),
            top_k=candidate_limit,
        )

        if not hybrid_candidates:
            return []

        # 2. Score and sort candidates using the cross-encoder
        reranked_results = self.reranker_service.rerank(
            query=query.strip(),
            candidates=hybrid_candidates,
            top_k=top_k,
        )

        return reranked_results


