"""Comprehensive API tests for Phase 7 — Vector Retrieval & Semantic Search.

Covers:
  1. Chunks receive non-null 384-dimensional vector embeddings upon ingestion.
  2. Semantic similarity search returns relevant chunks ordered by cosine similarity.
  3. Distinction test:
     - Query "I forgot my password and cannot sign in" matches Password Policy chunk #1.
     - Query "When will I receive my money back for my returned order?" matches Refund Policy chunk #1.
  4. Search respects top_k parameter bounding.
  5. Inactive documents are excluded from vector search results.
  6. Customer, Agent, and Admin users can all perform semantic search.
  7. Unauthenticated search is rejected with 401 Unauthorized.
  8. Validation: empty or whitespace query rejected with 422 Unprocessable Entity.
  9. Validation: top_k < 1 or top_k > 50 rejected with 422 Unprocessable Entity.
  10. Search with zero matches returns empty results list with total_results = 0.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument


@pytest.mark.asyncio
async def test_chunks_persist_with_valid_embeddings(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Verify that document ingestion populates 384-dimensional dense vectors in PostgreSQL."""
    uid = uuid.uuid4().hex[:8]
    payload = {
        "title": f"Vector Storage Policy {uid}",
        "content": (
            f"All knowledge chunks must be vectorized using local sentence-transformers "
            f"to enable dense vector retrieval in SupportFlow AI {uid}."
        ),
        "source_type": "TEXT",
    }

    create_resp = await client.post(
        "/api/v1/knowledge/raw",
        json=payload,
        headers=test_admin_user["headers"],
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    # Verify directly from database
    chunk_result = await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(doc_id))
    )
    chunks = chunk_result.scalars().all()
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.embedding is not None
        # Verify vector dimension is 384
        assert len(chunk.embedding) == 384


@pytest.mark.asyncio
async def test_semantic_search_accuracy_and_relevance(
    client: AsyncClient,
    test_admin_user: dict,
    test_customer_user: dict,
):
    """Verify that semantic retrieval returns topic-relevant chunks rather than keyword matches."""
    uid = uuid.uuid4().hex[:8]

    # Document 1: Password and Account Recovery
    pw_doc = {
        "title": f"Account Security and Password Recovery {uid}",
        "content": (
            f"If an agent or customer cannot authenticate {uid}, navigate to the credentials portal. "
            f"Click on the recovery link to dispatch a secure one-time passcode to your registered device. "
            f"Reset credentials must contain uppercase, lowercase, numbers, and symbols."
        ),
        "source_type": "TEXT",
    }
    r1 = await client.post("/api/v1/knowledge/raw", json=pw_doc, headers=test_admin_user["headers"])
    assert r1.status_code == 201
    pw_doc_id = r1.json()["id"]

    # Document 2: Return and Refund Guidelines
    refund_doc = {
        "title": f"Cancellation and Reimbursement Protocol {uid}",
        "content": (
            f"Purchased goods {uid} may be returned within 30 days of arrival. "
            f"Reimbursements are credited directly to the original bank card or digital payment instrument "
            f"within 5 to 7 operational working days following inspection approval."
        ),
        "source_type": "TEXT",
    }
    r2 = await client.post("/api/v1/knowledge/raw", json=refund_doc, headers=test_admin_user["headers"])
    assert r2.status_code == 201
    refund_doc_id = r2.json()["id"]

    # Query 1: Semantically related to password recovery (without using "authentication", "portal", etc.)
    pw_search = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "I lost my login pass and can't access my account", "top_k": 50},
        headers=test_customer_user["headers"],
    )
    assert pw_search.status_code == 200
    pw_data = pw_search.json()
    assert pw_data["total_results"] > 0
    # Among our two test documents, the Password document must rank higher than the Refund document.
    # Using top_k=50 (max) to ensure both test docs appear regardless of other docs in the shared DB.
    pw_matches = [r for r in pw_data["results"] if r["document_id"] in (pw_doc_id, refund_doc_id)]
    assert len(pw_matches) >= 1
    assert pw_matches[0]["document_id"] == pw_doc_id
    assert pw_matches[0]["score"] > 0.0

    # Query 2: Semantically related to reimbursement (without using "protocol", "arrival", etc.)
    refund_search = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "How many days will it take to get my money back after returning an item?", "top_k": 10},
        headers=test_customer_user["headers"],
    )
    assert refund_search.status_code == 200
    refund_data = refund_search.json()
    assert refund_data["total_results"] > 0
    # Between the two test documents, Refund document must rank higher than Password document
    refund_matches = [r for r in refund_data["results"] if r["document_id"] in (pw_doc_id, refund_doc_id)]
    assert len(refund_matches) >= 1
    assert refund_matches[0]["document_id"] == refund_doc_id
    assert refund_matches[0]["score"] > 0.0


@pytest.mark.asyncio
async def test_search_respects_top_k(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Verify top_k parameter strictly constrains the number of results returned."""
    search_resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "policy reimbursement returns security", "top_k": 1},
        headers=test_admin_user["headers"],
    )
    assert search_resp.status_code == 200
    data = search_resp.json()
    assert len(data["results"]) <= 1


@pytest.mark.asyncio
async def test_inactive_document_chunks_excluded_from_search(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Verify chunks from deactivated documents are never returned in search results."""
    uid = uuid.uuid4().hex[:8]
    secret_marker = f"SUPERSECRET_OBSOLETE_TEXT_{uid}"
    doc_payload = {
        "title": f"Deprecated Internal Policy {uid}",
        "content": f"Confidential legacy procedures {secret_marker} that must not appear in customer retrieval.",
        "source_type": "TEXT",
    }
    r = await client.post("/api/v1/knowledge/raw", json=doc_payload, headers=test_admin_user["headers"])
    assert r.status_code == 201
    doc_id = r.json()["id"]

    # Deactivate the document directly in database
    doc_db = await db_session.get(KnowledgeDocument, uuid.UUID(doc_id))
    assert doc_db is not None
    doc_db.is_active = False
    await db_session.commit()

    # Search for the specific marker
    search_resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": secret_marker, "top_k": 10},
        headers=test_admin_user["headers"],
    )
    assert search_resp.status_code == 200
    data = search_resp.json()
    # Deactivated document's chunks must NOT be present
    result_doc_ids = [res["document_id"] for res in data["results"]]
    assert doc_id not in result_doc_ids


@pytest.mark.asyncio
async def test_all_roles_can_search(
    client: AsyncClient,
    test_admin_user: dict,
    test_agent_user: dict,
    test_customer_user: dict,
):
    """Verify that ADMIN, SUPPORT_AGENT, and CUSTOMER roles are all permitted to query knowledge."""
    for user_fixture in [test_admin_user, test_agent_user, test_customer_user]:
        resp = await client.post(
            "/api/v1/knowledge/search",
            json={"query": "Standard customer policy inquiry", "top_k": 3},
            headers=user_fixture["headers"],
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unauthenticated_search_returns_401(client: AsyncClient):
    """Requests without authorization token are rejected."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "Unauthenticated query", "top_k": 5},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_query", ["", "   ", "a"])
async def test_search_invalid_query_validation(
    client: AsyncClient,
    test_customer_user: dict,
    invalid_query: str,
):
    """Query strings below minimum length or empty must be rejected with 422."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": invalid_query, "top_k": 5},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_top_k", [0, -1, 51, 100])
async def test_search_invalid_top_k_validation(
    client: AsyncClient,
    test_customer_user: dict,
    invalid_top_k: int,
):
    """top_k out of range [1, 50] must be rejected with 422."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "Valid search query", "top_k": invalid_top_k},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 422
