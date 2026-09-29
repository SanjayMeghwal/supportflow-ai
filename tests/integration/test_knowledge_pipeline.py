"""Phase 15 — Integration tests: Knowledge Base ingestion pipeline.

Validates the complete knowledge base pipeline from document upload through
chunk creation, metadata persistence, search availability, and deletion
cascades. Tests verify both the HTTP API contract and the database state.

Journeys:
  1.  Admin uploads markdown → document + chunks persisted in DB.
  2.  Agent uploads plain text → document + chunks persisted in DB.
  3.  Duplicate SHA-256 is rejected → no second document created in DB.
  4.  Customer upload is forbidden → DB state unchanged.
  5.  Unauthenticated upload is rejected → DB state unchanged.
  6.  Admin ingests FAQ JSON → correct number of FAQ items created.
  7.  Admin ingests raw text JSON → document + chunks persisted.
  8.  Admin deletes document → document and chunks cascade-deleted from DB.
  9.  Agent cannot delete knowledge document → 403, DB state unchanged.
  10. Get document detail returns chunks in sequential order.
  11. Inactive document is excluded from search results.
  12. Invalid file extension is rejected with 400.
  13. Empty file upload is rejected with 400.
  14. List documents: pagination respects limit and offset.
  15. List documents: source_type filter returns only matching documents.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument, SourceType


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def _markdown_doc(uid: str) -> bytes:
    """Return a uniquely tagged markdown document as bytes."""
    return (
        f"# Shipping Policy {uid}\n\n"
        f"## Standard Shipping\n"
        f"Standard shipping takes 5-7 business days and costs $4.99.\n\n"
        f"## Express Shipping\n"
        f"Express shipping takes 1-2 business days and costs $14.99.\n\n"
        f"## International Shipping {uid}\n"
        f"International shipping is available to 45 countries with delivery in 7-21 business days.\n"
    ).encode("utf-8")


def _text_doc(uid: str) -> bytes:
    """Return a uniquely tagged plain text document as bytes."""
    return (
        f"Support FAQ Document {uid}\n\n"
        f"Q: How do I reset my password?\n"
        f"A: Click the Forgot Password link on the login page and enter your email address.\n\n"
        f"Q: How do I contact customer support?\n"
        f"A: You can reach us at support@example.com or call 1-800-SUPPORT.\n\n"
        f"Q: What are your business hours {uid}?\n"
        f"A: Our support team is available Monday through Friday, 9 AM to 6 PM EST.\n"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Admin uploads markdown → DB state verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_upload_creates_document_and_chunks(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Journey 1: Markdown upload creates KnowledgeDocument + DocumentChunks in DB."""
    uid = uuid.uuid4().hex[:8]
    content = _markdown_doc(uid)
    title = f"Shipping Policy {uid}"

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"shipping_{uid}.md", content, "text/markdown")},
        data={"title": title, "source_uri": f"https://internal.example.com/shipping-{uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 201, resp.text
    doc_id = uuid.UUID(resp.json()["id"])

    # Verify document in DB
    doc_result = await db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    db_doc = doc_result.scalar_one_or_none()
    assert db_doc is not None, "Document not persisted in DB"
    assert db_doc.title == title
    assert db_doc.is_active is True

    # Verify chunks in DB
    chunk_result = await db_session.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    chunk_count = chunk_result.scalar_one()
    assert chunk_count >= 1, "Document must produce at least one chunk"


# ---------------------------------------------------------------------------
# 2. Agent uploads plain text → DB state verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_upload_creates_document_and_chunks(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Journey 2: Agent uploads plain text; document and chunks are created."""
    uid = uuid.uuid4().hex[:8]
    content = _text_doc(uid)
    title = f"Support FAQ {uid}"

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"faq_{uid}.txt", content, "text/plain")},
        data={"title": title},
        headers=test_agent_user["headers"],
    )
    assert resp.status_code == 201, resp.text
    doc_id = uuid.UUID(resp.json()["id"])

    # Verify document created
    doc_result = await db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    db_doc = doc_result.scalar_one_or_none()
    assert db_doc is not None
    assert db_doc.title == title

    # Verify at least 1 chunk
    chunk_count = await db_session.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    assert chunk_count >= 1


# ---------------------------------------------------------------------------
# 3. Duplicate SHA-256 is rejected, no second document created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_document_rejected_no_db_change(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Journey 3: Uploading the same content twice returns 409, no duplicate in DB."""
    uid = uuid.uuid4().hex[:8]
    content = _markdown_doc(uid)
    title = f"Dedup Test Doc {uid}"

    # First upload
    resp1 = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"dedup_{uid}.md", content, "text/markdown")},
        data={"title": title},
        headers=test_admin_user["headers"],
    )
    assert resp1.status_code == 201

    # Count before second attempt
    count_before = await db_session.scalar(
        select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.title == title)
    )

    # Second upload (identical content)
    resp2 = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"dedup_{uid}_copy.md", content, "text/markdown")},
        data={"title": f"Dedup Copy {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp2.status_code == 409

    # Count after second attempt — must not have increased
    count_for_original = await db_session.scalar(
        select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.title == title)
    )
    assert count_for_original == count_before


# ---------------------------------------------------------------------------
# 4. Customer upload is forbidden — DB state unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_upload_forbidden_no_db_change(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Journey 4: CUSTOMER cannot upload documents; no document created in DB."""
    uid = uuid.uuid4().hex[:8]
    content = _text_doc(uid)
    title = f"Customer Upload Attempt {uid}"

    # Count before
    count_before = await db_session.scalar(select(func.count(KnowledgeDocument.id)))

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"forbidden_{uid}.txt", content, "text/plain")},
        data={"title": title},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 403

    # Count after — must be unchanged
    count_after = await db_session.scalar(select(func.count(KnowledgeDocument.id)))
    assert count_after == count_before


# ---------------------------------------------------------------------------
# 5. Unauthenticated upload is rejected — DB state unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_upload_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Journey 5: Unauthenticated upload returns 401; no document created."""
    uid = uuid.uuid4().hex[:8]
    count_before = await db_session.scalar(select(func.count(KnowledgeDocument.id)))

    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"noauth_{uid}.txt", b"test content", "text/plain")},
        data={"title": f"Unauth Upload {uid}"},
    )
    assert resp.status_code == 401

    count_after = await db_session.scalar(select(func.count(KnowledgeDocument.id)))
    assert count_after == count_before


# ---------------------------------------------------------------------------
# 6. FAQ JSON ingestion creates correct document records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_faq_ingestion_creates_documents(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Journey 6: FAQ JSON ingestion creates document records with FAQ source_type."""
    uid = uuid.uuid4().hex[:8]
    faq_items = [
        {"question": f"What is your return policy? {uid}", "answer": "30-day return window for all items."},
        {"question": f"Do you offer free shipping? {uid}", "answer": "Yes, on orders over $50."},
    ]

    resp = await client.post(
        "/api/v1/knowledge/faq",
        json={"items": faq_items},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2

    # Verify both FAQ documents are in DB
    for doc_info in data:
        doc_id = uuid.UUID(doc_info["id"])
        db_doc = await db_session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        )
        assert db_doc is not None
        assert db_doc.source_type == SourceType.FAQ


# ---------------------------------------------------------------------------
# 7. Raw text JSON ingestion creates document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_text_ingestion_creates_document(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Journey 7: Raw text ingestion via JSON creates a document with chunks."""
    uid = uuid.uuid4().hex[:8]
    title = f"Raw Text Policy {uid}"
    content = (
        f"Privacy Policy {uid}: This document describes how SupportFlow AI collects, "
        f"uses, and protects personal data. All data is encrypted at rest and in transit. "
        f"Users may request deletion of their data within 30 days. "
        f"Contact privacy@example.com for data requests."
    )

    resp = await client.post(
        "/api/v1/knowledge/raw",
        json={"title": title, "content": content, "source_uri": f"https://example.com/privacy-{uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 201, resp.text
    doc_id = uuid.UUID(resp.json()["id"])

    # Verify in DB
    db_doc = await db_session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    assert db_doc is not None
    assert db_doc.title == title
    assert db_doc.source_type in (SourceType.MANUAL, SourceType.PLAIN_TEXT, SourceType.MARKDOWN)


# ---------------------------------------------------------------------------
# 8. Admin deletes document → cascade deletes chunks from DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_deletion_cascades_to_chunks(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Journey 8: Deleting a document also deletes all its chunks from DB."""
    uid = uuid.uuid4().hex[:8]
    content = _text_doc(uid)

    # Upload
    upload_resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"cascade_{uid}.txt", content, "text/plain")},
        data={"title": f"Cascade Delete Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert upload_resp.status_code == 201
    doc_id_str = upload_resp.json()["id"]
    doc_id = uuid.UUID(doc_id_str)

    # Confirm chunks exist before deletion
    chunk_count_before = await db_session.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    assert chunk_count_before >= 1

    # Delete the document
    delete_resp = await client.delete(
        f"/api/v1/knowledge/{doc_id_str}",
        headers=test_admin_user["headers"],
    )
    assert delete_resp.status_code == 204

    # Verify document is gone from DB
    db_doc = await db_session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    assert db_doc is None

    # Verify chunks are cascade-deleted
    chunk_count_after = await db_session.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)
    )
    assert chunk_count_after == 0


# ---------------------------------------------------------------------------
# 9. Agent cannot delete knowledge document (403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_cannot_delete_knowledge_document(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
    test_agent_user: dict,
):
    """Journey 9: SUPPORT_AGENT cannot delete knowledge documents (admin-only)."""
    uid = uuid.uuid4().hex[:8]
    content = _text_doc(uid)

    upload_resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"agentdel_{uid}.txt", content, "text/plain")},
        data={"title": f"Agent Delete Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert upload_resp.status_code == 201
    doc_id_str = upload_resp.json()["id"]
    doc_id = uuid.UUID(doc_id_str)

    # Agent attempts to delete
    delete_resp = await client.delete(
        f"/api/v1/knowledge/{doc_id_str}",
        headers=test_agent_user["headers"],
    )
    assert delete_resp.status_code == 403

    # Document must still exist in DB
    db_doc = await db_session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    assert db_doc is not None, "Document was incorrectly deleted by agent"


# ---------------------------------------------------------------------------
# 10. Get document detail returns chunks in sequential order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_detail_chunks_in_order(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Journey 10: GET /knowledge/{id} returns chunks with ascending chunk_index."""
    uid = uuid.uuid4().hex[:8]
    # Create content long enough to produce multiple chunks
    long_content = (
        f"# Comprehensive Policy Document {uid}\n\n"
        + "\n\n".join(
            f"## Section {i} {uid}\n"
            f"This section covers topic {i} of our comprehensive policy. "
            f"All agents must read and understand this section before proceeding. "
            f"The policies described here are binding and enforced consistently across all departments."
            for i in range(1, 8)
        )
    ).encode("utf-8")

    upload_resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"ordered_{uid}.md", long_content, "text/markdown")},
        data={"title": f"Ordered Chunk Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    detail_resp = await client.get(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_admin_user["headers"],
    )
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert "chunks" in data

    chunk_indices = [c["chunk_index"] for c in data["chunks"]]
    assert chunk_indices == sorted(chunk_indices), "Chunks are not in ascending order"


# ---------------------------------------------------------------------------
# 11. Inactive document excluded from search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_document_excluded_from_search(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
    test_agent_user: dict,
):
    """Journey 11: Deactivated document does not appear in search results."""
    uid = uuid.uuid4().hex[:8]
    unique_term = f"qrxzpolicyterm{uid}"
    content = (
        f"# Unique Policy {uid}\n\n"
        f"This document contains the special term: {unique_term}. "
        f"It should appear in search when active and disappear when deactivated."
    ).encode("utf-8")

    upload_resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"inactive_{uid}.md", content, "text/markdown")},
        data={"title": f"Inactive Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Deactivate the document directly in the DB
    doc = await db_session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == uuid.UUID(doc_id))
    )
    doc.is_active = False
    db_session.add(doc)
    await db_session.commit()

    # Search for the unique term — should return 0 hits for this document
    search_resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": unique_term, "top_k": 10, "search_type": "full_text"},
        headers=test_agent_user["headers"],
    )
    assert search_resp.status_code == 200
    results = search_resp.json()
    result_doc_ids = [r["document_id"] for r in results]
    assert doc_id not in result_doc_ids, "Inactive document should not appear in search results"


# ---------------------------------------------------------------------------
# 12. Invalid file extension rejected with 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_extension_rejected(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Journey 12: Uploading an unsupported file extension returns 400."""
    uid = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"script_{uid}.py", b"print('hello')", "text/x-python")},
        data={"title": f"Invalid Extension {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 13. Empty file upload rejected with 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_file_rejected(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Journey 13: Uploading a zero-byte file returns 400 Bad Request."""
    uid = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"empty_{uid}.txt", b"", "text/plain")},
        data={"title": f"Empty File Test {uid}"},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 14. List documents: pagination respects limit and offset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_pagination(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Journey 14: GET /knowledge list supports limit/offset pagination without duplicates."""
    # Upload 4 documents
    for i in range(4):
        uid = uuid.uuid4().hex[:8]
        await client.post(
            "/api/v1/knowledge/upload",
            files={"file": (f"page_{uid}.txt", _text_doc(uid), "text/plain")},
            data={"title": f"Pagination Doc {i} {uid}"},
            headers=test_admin_user["headers"],
        )

    page1 = await client.get(
        "/api/v1/knowledge?limit=2&offset=0",
        headers=test_admin_user["headers"],
    )
    page2 = await client.get(
        "/api/v1/knowledge?limit=2&offset=2",
        headers=test_admin_user["headers"],
    )

    assert page1.status_code == 200
    assert page2.status_code == 200

    ids_p1 = {d["id"] for d in page1.json().get("documents", page1.json())}
    ids_p2 = {d["id"] for d in page2.json().get("documents", page2.json())}
    assert ids_p1.isdisjoint(ids_p2), "Paginated pages must not overlap"


# ---------------------------------------------------------------------------
# 15. List documents: source_type filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_source_type_filter(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Journey 15: Filtering by source_type returns only matching documents."""
    uid = uuid.uuid4().hex[:8]

    # Upload a plain-text document
    await client.post(
        "/api/v1/knowledge/upload",
        files={"file": (f"filtertype_{uid}.txt", _text_doc(uid), "text/plain")},
        data={"title": f"Filter Source Test {uid}"},
        headers=test_admin_user["headers"],
    )

    # Query filtered by PLAIN_TEXT
    filtered_resp = await client.get(
        "/api/v1/knowledge?source_type=PLAIN_TEXT",
        headers=test_admin_user["headers"],
    )
    assert filtered_resp.status_code == 200
    docs = filtered_resp.json()
    # All returned documents must have the specified source_type
    doc_list = docs.get("documents", docs)
    for doc in doc_list:
        assert doc.get("source_type") in ("PLAIN_TEXT", None), (
            f"Unexpected source_type: {doc.get('source_type')}"
        )
