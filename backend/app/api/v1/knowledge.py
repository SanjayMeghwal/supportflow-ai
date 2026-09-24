"""Knowledge Base REST API endpoints for document ingestion and management."""

import json
from pathlib import Path
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, require_admin, require_support_agent
from backend.app.core.database import get_db
from backend.app.models.knowledge import KnowledgeDocument, SourceType
from backend.app.models.user import User
from backend.app.schemas.knowledge import (
    DocumentChunkResponse,
    FAQDocumentCreateRequest,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    TextDocumentCreateRequest,
)
from backend.app.services.extractors import ExtractionError
from backend.app.services.knowledge import DuplicateDocumentError, KnowledgeService

router = APIRouter()
knowledge_service = KnowledgeService()

# Maximum allowed file size: 10 MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt", ".text", ".json"}


def _document_to_response(doc: KnowledgeDocument, chunk_count: int = 0) -> KnowledgeDocumentResponse:
    """Helper to convert KnowledgeDocument model to KnowledgeDocumentResponse."""
    return KnowledgeDocumentResponse(
        id=doc.id,
        title=doc.title,
        source_type=doc.source_type,
        source_uri=doc.source_uri,
        checksum_sha256=doc.checksum_sha256,
        is_active=doc.is_active,
        chunk_count=chunk_count,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /knowledge/upload — Ingest Document File (PDF, Markdown, Text, FAQ)
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a knowledge document file",
    responses={
        400: {"description": "Invalid file format or corrupted content"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        409: {"description": "Conflict — duplicate document already exists"},
        413: {"description": "Payload Too Large — file exceeds 10MB limit"},
    },
)
async def upload_document(
    file: UploadFile = File(..., description="Document file (.pdf, .md, .txt, .json)"),
    title: str = Form(..., min_length=3, max_length=255, description="Document title"),
    source_type: Optional[SourceType] = Form(default=None, description="Explicit source type"),
    source_uri: Optional[str] = Form(default=None, max_length=512, description="Optional origin URL"),
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """Ingest a knowledge document file into chunks for RAG.

    - Validates file extension against allowed formats.
    - Enforces 10MB maximum upload limit.
    - Computes SHA-256 checksum and prevents duplicate ingestion.
    - Chunks content deterministically for downstream vector retrieval.
    """
    filename = file.filename or "document.txt"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read file content with size bounding
    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
        )
    if not content_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        doc = await knowledge_service.ingest_document(
            db=db,
            title=title.strip(),
            content_bytes=content_bytes,
            filename=filename,
            source_type=source_type,
            source_uri=source_uri.strip() if source_uri else None,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document with identical content already exists (ID: {exc.existing_document_id}).",
        ) from exc
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Refresh document to get chunks count
    doc_detail = await knowledge_service.get_document_detail(db, doc.id)
    chunk_count = len(doc_detail.chunks) if doc_detail else 0
    return _document_to_response(doc, chunk_count=chunk_count)


# ---------------------------------------------------------------------------
# POST /knowledge/raw — Ingest Plain Text or Markdown via JSON
# ---------------------------------------------------------------------------


@router.post(
    "/raw",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest raw text or markdown content",
    responses={
        400: {"description": "Invalid text content"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        409: {"description": "Conflict — duplicate document already exists"},
    },
)
async def ingest_raw_text(
    payload: TextDocumentCreateRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """Ingest a text or markdown document directly via JSON payload."""
    content_bytes = payload.content.encode("utf-8")
    ext = ".md" if payload.source_type == SourceType.MARKDOWN else ".txt"
    filename = f"{payload.title.lower().replace(' ', '_')[:30]}{ext}"

    try:
        doc = await knowledge_service.ingest_document(
            db=db,
            title=payload.title.strip(),
            content_bytes=content_bytes,
            filename=filename,
            source_type=payload.source_type,
            source_uri=payload.source_uri,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document with identical content already exists (ID: {exc.existing_document_id}).",
        ) from exc
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    doc_detail = await knowledge_service.get_document_detail(db, doc.id)
    chunk_count = len(doc_detail.chunks) if doc_detail else 0
    return _document_to_response(doc, chunk_count=chunk_count)


# ---------------------------------------------------------------------------
# POST /knowledge/faq — Ingest Structured FAQ Collection
# ---------------------------------------------------------------------------


@router.post(
    "/faq",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest structured FAQ collection",
    responses={
        400: {"description": "Invalid FAQ format"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        409: {"description": "Conflict — duplicate document already exists"},
    },
)
async def ingest_faq_collection(
    payload: FAQDocumentCreateRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """Ingest structured question-answer pairs into knowledge chunks."""
    faq_data = [{"question": item.question, "answer": item.answer} for item in payload.faqs]
    content_bytes = json.dumps(faq_data, indent=2).encode("utf-8")
    filename = f"{payload.title.lower().replace(' ', '_')[:30]}.json"

    try:
        doc = await knowledge_service.ingest_document(
            db=db,
            title=payload.title.strip(),
            content_bytes=content_bytes,
            filename=filename,
            source_type=SourceType.FAQ,
            source_uri=payload.source_uri,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document with identical content already exists (ID: {exc.existing_document_id}).",
        ) from exc
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    doc_detail = await knowledge_service.get_document_detail(db, doc.id)
    chunk_count = len(doc_detail.chunks) if doc_detail else 0
    return _document_to_response(doc, chunk_count=chunk_count)


# ---------------------------------------------------------------------------
# GET /knowledge — List Ingested Documents
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=KnowledgeDocumentListResponse,
    summary="List ingested knowledge documents",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    source_type: Optional[SourceType] = Query(default=None, description="Filter by source format"),
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
) -> KnowledgeDocumentListResponse:
    """List knowledge base documents with chunk counts and pagination."""
    items, total = await knowledge_service.list_documents(
        db=db,
        offset=offset,
        limit=limit,
        source_type=source_type,
        is_active=is_active,
    )

    documents = [_document_to_response(doc, chunk_count=count) for doc, count in items]
    return KnowledgeDocumentListResponse(
        documents=documents,
        total=total,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /knowledge/{document_id} — Retrieve Document Detail & Chunks
# ---------------------------------------------------------------------------


@router.get(
    "/{document_id}",
    response_model=KnowledgeDocumentDetailResponse,
    summary="Get document details including chunks",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found"},
    },
)
async def get_document_detail(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentDetailResponse:
    """Fetch knowledge document metadata and all constituent chunks in sequence."""
    doc = await knowledge_service.get_document_detail(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )

    chunks = [
        DocumentChunkResponse(
            id=c.id,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
            chunk_text=c.chunk_text,
            metadata_json=c.metadata_json,
            created_at=c.created_at,
        )
        for c in doc.chunks
    ]

    return KnowledgeDocumentDetailResponse(
        id=doc.id,
        title=doc.title,
        source_type=doc.source_type,
        source_uri=doc.source_uri,
        checksum_sha256=doc.checksum_sha256,
        is_active=doc.is_active,
        chunk_count=len(chunks),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunks=chunks,
    )


# ---------------------------------------------------------------------------
# DELETE /knowledge/{document_id} — Delete Document (Admin Only)
# ---------------------------------------------------------------------------


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete knowledge document and its chunks",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires ADMIN role"},
        404: {"description": "Document not found"},
    },
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a knowledge document and its associated chunks from the system."""
    deleted = await knowledge_service.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found.",
        )
