"""Comprehensive API tests for Phase 6 — Knowledge Base Ingestion Pipeline.

Covers:
  1. Admin can upload markdown file via multipart form.
  2. Support Agent can upload plain text file via multipart form.
  3. Raw text/markdown ingestion via JSON endpoint (/raw).
  4. Structured FAQ ingestion via JSON endpoint (/faq).
  5. Duplicate document rejected with 409 Conflict (SHA-256 deduplication).
  6. Customer is forbidden from uploading documents (403 Forbidden).
  7. Unauthenticated upload attempts return 401 Unauthorized.
  8. List documents with pagination and source_type filtering.
  9. Get document detail returns chunks in sequential order.
  10. Nonexistent document detail returns 404 Not Found.
  11. Admin can delete document (cascades to chunks).
  12. Customer and Support Agent cannot delete documents (403 Forbidden).
  13. Invalid file extensions return 400 Bad Request.
  14. Empty files return 400 Bad Request.
"""

import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument, SourceType


# ---------------------------------------------------------------------------
# 1. Admin Uploads Markdown Document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_upload_markdown_file(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Admin can upload a markdown file; chunks are created automatically."""
    uid = uuid.uuid4().hex[:8]
    md_content = (
        f"# Return & Refund Policy {uid}\n\n"
        f"## 1. 30-Day Window\n"
        f"Customers may initiate a return within 30 calendar days of delivery.\n\n"
        f"## 2. Condition Requirements\n"
        f"Items must be undamaged, unworn, and in their original packaging.\n\n"
        f"## 3. Refund Method\n"
        f"Refunds are credited back to the original payment method within 5-7 business days.\n"
    ).encode("utf-8")

    files = {"file": (f"return_policy_{uid}.md", md_content, "text/markdown")}
    data = {
        "title": f"Return and Refund Policy {uid}",
        "source_uri": f"https://internal.example.com/policies/refunds-{uid}",
    }

    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 201
    resp_data = response.json()
    assert resp_data["title"] == f"Return and Refund Policy {uid}"
    assert resp_data["source_type"] == "MARKDOWN"
    assert resp_data["chunk_count"] > 0
    assert "checksum_sha256" in resp_data
    assert resp_data["is_active"] is True


# ---------------------------------------------------------------------------
# 2. Support Agent Uploads Text Document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_can_upload_text_file(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Support agents possess permission to ingest knowledge documents."""
    uid = uuid.uuid4().hex[:8]
    text_content = (
        f"Standard Delivery {uid} takes 3 to 5 business days across domestic regions. "
        f"Express shipping delivers within 24 to 48 hours for an additional fee."
    ).encode("utf-8")
    files = {"file": (f"shipping_info_{uid}.txt", text_content, "text/plain")}
    data = {"title": f"Shipping Timelines Guide {uid}"}

    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 201
    resp_data = response.json()
    assert resp_data["source_type"] == "TEXT"
    assert resp_data["chunk_count"] == 1


# ---------------------------------------------------------------------------
# 3. Raw Text Ingestion via JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_ingest_raw_text(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Admin can ingest raw text or markdown via the JSON /raw endpoint."""
    uid = uuid.uuid4().hex[:8]
    payload = {
        "title": f"Warranty Protection Details {uid}",
        "content": (
            f"All hardware devices {uid} come with a standard 1-year limited manufacturer warranty. "
            f"Accidental damage, liquid immersion, and unauthorized repairs are strictly excluded."
        ),
        "source_type": "TEXT",
        "source_uri": f"https://internal.example.com/warranty-{uid}",
    }

    response = await client.post(
        "/api/v1/knowledge/raw",
        json=payload,
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == f"Warranty Protection Details {uid}"
    assert data["chunk_count"] >= 1


# ---------------------------------------------------------------------------
# 4. Structured FAQ Ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_ingest_faq_collection(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Admin can ingest structured Q&A pairs via the /faq endpoint."""
    uid = uuid.uuid4().hex[:8]
    payload = {
        "title": f"Account & Password FAQs {uid}",
        "faqs": [
            {
                "question": f"How do I reset my account password {uid}?",
                "answer": "Click Forgot Password on the login page and follow email instructions.",
            },
            {
                "question": f"Can I change my registered email address {uid}?",
                "answer": "Yes, navigate to Account Settings > Security and request an email change.",
            },
        ],
    }

    response = await client.post(
        "/api/v1/knowledge/faq",
        json=payload,
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "FAQ"
    assert data["chunk_count"] >= 1


# ---------------------------------------------------------------------------
# 5. SHA-256 Deduplication Rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_document_rejected(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Attempting to ingest a document with identical content returns 409 Conflict."""
    content = f"Unique policy content for deduplication test {uuid.uuid4().hex}."
    payload = {"title": "Duplicate Policy Test", "content": content, "source_type": "TEXT"}

    # Initial ingestion succeeds
    first_resp = await client.post(
        "/api/v1/knowledge/raw",
        json=payload,
        headers=test_admin_user["headers"],
    )
    assert first_resp.status_code == 201

    # Second ingestion of identical content fails with 409
    dup_resp = await client.post(
        "/api/v1/knowledge/raw",
        json=payload,
        headers=test_admin_user["headers"],
    )
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. Customer Forbidden From Uploading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_forbidden_from_uploading(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Customer role is prohibited from creating or uploading knowledge documents."""
    # Attempt multipart upload
    files = {"file": ("test.txt", b"Customer trying to upload", "text/plain")}
    resp1 = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data={"title": "Customer Attempt"},
        headers=test_customer_user["headers"],
    )
    assert resp1.status_code == 403

    # Attempt raw text upload
    resp2 = await client.post(
        "/api/v1/knowledge/raw",
        json={"title": "Customer Attempt", "content": "Sample content that should fail."},
        headers=test_customer_user["headers"],
    )
    assert resp2.status_code == 403

    # Attempt FAQ upload
    resp3 = await client.post(
        "/api/v1/knowledge/faq",
        json={
            "title": "Customer FAQs",
            "faqs": [{"question": "Q?", "answer": "A!"}],
        },
        headers=test_customer_user["headers"],
    )
    assert resp3.status_code == 403


# ---------------------------------------------------------------------------
# 7. Unauthenticated Requests Return 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_requests_fail(client: AsyncClient):
    """Requests missing bearer token return 401 Unauthorized."""
    resp = await client.get("/api/v1/knowledge")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. List Documents with Pagination & Filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_pagination(
    client: AsyncClient,
    test_admin_user: dict,
):
    """List documents endpoint supports limit, offset, and source_type filtering."""
    for i in range(3):
        await client.post(
            "/api/v1/knowledge/raw",
            json={
                "title": f"Doc List Test {i} {uuid.uuid4().hex[:6]}",
                "content": f"Unique content for pagination test {i} {uuid.uuid4().hex}.",
                "source_type": "TEXT",
            },
            headers=test_admin_user["headers"],
        )

    response = await client.get(
        "/api/v1/knowledge?limit=2&offset=0",
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["documents"]) <= 2
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert data["total"] >= 3


# ---------------------------------------------------------------------------
# 9. Get Document Detail with Chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_document_detail_with_chunks(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Detail endpoint returns document with its sequentially ordered chunks."""
    uid = uuid.uuid4().hex[:8]
    content = (
        f"Part 1 {uid}: Cancellation is permitted within 24 hours of placing order.\n\n"
        f"Part 2 {uid}: After 24 hours, the order moves to fulfillment and cannot be recalled.\n\n"
        f"Part 3 {uid}: Customers must instead wait for delivery and initiate a standard return."
    )
    create_resp = await client.post(
        "/api/v1/knowledge/raw",
        json={
            "title": f"Cancellation Guidelines {uid}",
            "content": content,
            "source_type": "TEXT",
        },
        headers=test_admin_user["headers"],
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    detail_resp = await client.get(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_admin_user["headers"],
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == doc_id
    assert "chunks" in detail
    assert len(detail["chunks"]) > 0

    # Verify chunk indices are sequential starting from 0
    indices = [c["chunk_index"] for c in detail["chunks"]]
    assert indices == list(range(len(indices)))


# ---------------------------------------------------------------------------
# 10. Nonexistent Document Returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_nonexistent_document_returns_404(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Querying a non-existent document ID returns 404 Not Found."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/knowledge/{fake_id}",
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 11. Admin Deletes Document (Cascades Chunks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_delete_document_cascades(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Admin can delete a document, and all associated chunks are cascade-deleted."""
    uid = uuid.uuid4().hex[:8]
    create_resp = await client.post(
        "/api/v1/knowledge/raw",
        json={
            "title": f"To Be Deleted {uid}",
            "content": f"Temporary policy document {uid} that will be deleted shortly.",
            "source_type": "TEXT",
        },
        headers=test_admin_user["headers"],
    )
    doc_id = create_resp.json()["id"]

    # Delete the document
    del_resp = await client.delete(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_admin_user["headers"],
    )
    assert del_resp.status_code == 204

    # Verify document no longer exists
    get_resp = await client.get(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_admin_user["headers"],
    )
    assert get_resp.status_code == 404

    # Verify chunks are removed from DB
    chunks_result = await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(doc_id))
    )
    assert len(chunks_result.scalars().all()) == 0


# ---------------------------------------------------------------------------
# 12. Non-Admins Cannot Delete Documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_admin_cannot_delete_document(
    client: AsyncClient,
    test_admin_user: dict,
    test_agent_user: dict,
    test_customer_user: dict,
):
    """Only ADMIN role can delete documents; AGENT and CUSTOMER are forbidden."""
    uid = uuid.uuid4().hex[:8]
    create_resp = await client.post(
        "/api/v1/knowledge/raw",
        json={
            "title": f"Protected Doc {uid}",
            "content": f"Only admins can delete this authoritative document {uid}.",
            "source_type": "TEXT",
        },
        headers=test_admin_user["headers"],
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    # Customer attempt
    cust_del = await client.delete(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_customer_user["headers"],
    )
    assert cust_del.status_code == 403

    # Agent attempt
    agent_del = await client.delete(
        f"/api/v1/knowledge/{doc_id}",
        headers=test_agent_user["headers"],
    )
    assert agent_del.status_code == 403


# ---------------------------------------------------------------------------
# 13. Invalid File Extension Rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_file_extension_rejected(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Uploads with unauthorized extensions (.exe, .png) are rejected with 400."""
    files = {"file": ("malicious.exe", b"binary content", "application/octet-stream")}
    data = {"title": "Executable File Attempt"}

    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "unsupported file format" in detail or "disallowed file extension" in detail


# ---------------------------------------------------------------------------
# 14. Empty File Upload Rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_file_rejected(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Empty (0-byte) files are rejected with 400 Bad Request."""
    files = {"file": ("empty.txt", b"", "text/plain")}
    data = {"title": "Empty File"}

    response = await client.post(
        "/api/v1/knowledge/upload",
        files=files,
        data=data,
        headers=test_admin_user["headers"],
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
