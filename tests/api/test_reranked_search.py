"""Phase 9 API integration tests — Cross-Encoder Reranked Knowledge Search.

Test isolation strategy
-----------------------
Each test creates uniquely-identified documents (UUID hex suffix embedded in
title and chunk content) and asserts against its specific created document IDs.
This ensures robustness in shared database test environments without reliance on
arbitrary top_k workarounds.

Coverage
--------
1. test_reranked_search_success:
   Successful reranked search returns relevant chunk with full metadata (vector_rank,
   fts_rank, rrf_score, rerank_score).
2. test_reranked_inactive_document_excluded:
   Inactive documents are strictly excluded from reranked retrieval.
3. test_reranked_controlled_relevance_ordering:
   Controlled multi-document relevance test: Password reset vs. Refund vs. Shipping.
   Query targeting login issues correctly ranks the Password chunk first.
4. test_reranked_no_match_returns_empty:
   Queries with no matching candidates gracefully return 0 results and empty list.
5. test_reranked_top_k_bounds_results:
   top_k strictly bounds the final number of returned reranked results.
6. test_reranked_all_roles_can_search:
   ADMIN, SUPPORT_AGENT, and CUSTOMER roles are all authorized to use reranked search.
7. test_reranked_unauthenticated_returns_401:
   Unauthenticated search requests are rejected with 401 Unauthorized.
8. test_reranked_validation_empty_query_rejected:
   Empty or too-short queries are rejected with 422 Unprocessable Entity.
9. test_backward_compat_all_search_modes_coexist:
   Verifies vector (default), full_text, hybrid, and reranked all function correctly
   and preserve backward compatibility.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.knowledge import KnowledgeDocument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ingest_raw(client: AsyncClient, headers: dict, title: str, content: str) -> str:
    """Ingest a TEXT document and return its document_id string."""
    resp = await client.post(
        "/api/v1/knowledge/raw",
        json={"title": title, "content": content, "source_type": "TEXT"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Ingestion failed: {resp.text}"
    return resp.json()["id"]


async def _search(
    client: AsyncClient,
    headers: dict,
    query: str,
    search_type: str = "reranked",
    top_k: int = 5,
) -> dict:
    """Issue a knowledge search request and return the parsed JSON response."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "search_type": search_type, "top_k": top_k},
        headers=headers,
    )
    assert resp.status_code == 200, f"Search failed ({resp.status_code}): {resp.text}"
    return resp.json()


def _doc_ids_in_results(data: dict) -> list[str]:
    return [r["document_id"] for r in data["results"]]


# ---------------------------------------------------------------------------
# API Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reranked_search_success(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Reranked search returns matches with score, rerank_score, and upstream metadata."""
    uid = uuid.uuid4().hex[:8]
    title = f"Billing Disputes Protocol {uid}"
    content = (
        f"To dispute a charge or billing discrepancy {uid}, contact customer support "
        f"with your transaction receipt and statement within sixty calendar days."
    )
    doc_id = await _ingest_raw(client, test_admin_user["headers"], title, content)

    data = await _search(
        client,
        test_admin_user["headers"],
        query=f"dispute a charge {uid}",
        search_type="reranked",
        top_k=5,
    )

    assert data["search_type"] == "reranked"
    assert data["total_results"] >= 1

    doc_ids = _doc_ids_in_results(data)
    assert doc_id in doc_ids, f"Expected {doc_id} in results, got {doc_ids}"

    matched_item = next(r for r in data["results"] if r["document_id"] == doc_id)
    assert matched_item["score"] == matched_item["rerank_score"]
    assert isinstance(matched_item["rerank_score"], float)
    assert matched_item["rrf_score"] is not None
    assert isinstance(matched_item["rrf_score"], float)
    # vector_rank and fts_rank should be present as keys
    assert "vector_rank" in matched_item
    assert "fts_rank" in matched_item


@pytest.mark.asyncio
async def test_reranked_inactive_document_excluded(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Inactive documents must not appear in reranked search results."""
    uid = uuid.uuid4().hex[:8]
    marker = f"SECRET_RERANK_INACTIVE_{uid}"
    doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Inactive Rerank Doc {uid}",
        f"Confidential {marker} text that should never be surfaced by reranker.",
    )

    # Deactivate the document directly in database
    doc_db = await db_session.get(KnowledgeDocument, uuid.UUID(doc_id))
    assert doc_db is not None
    doc_db.is_active = False
    await db_session.commit()

    data = await _search(
        client,
        test_admin_user["headers"],
        query=marker,
        search_type="reranked",
        top_k=10,
    )

    assert doc_id not in _doc_ids_in_results(data), (
        "Inactive document appeared in reranked results"
    )


@pytest.mark.asyncio
async def test_reranked_controlled_relevance_ordering(
    client: AsyncClient,
    test_admin_user: dict,
    test_customer_user: dict,
):
    """Verify that cross-encoder correctly prioritizes the most relevant document.

    Ingest three documents:
    1. Password recovery
    2. Refund policy
    3. Shipping guidelines

    Query targeting password issues should place Password doc at rank 1
    among the controlled documents.
    """
    uid = uuid.uuid4().hex[:8]

    pw_doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Account Security & Password Recovery {uid}",
        (
            f"If you forgot your password {uid}, visit the identity portal to request a "
            f"secure verification email. Follow the link to reset your account credentials."
        ),
    )
    refund_doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Return & Refund Policy {uid}",
        (
            f"Customer refunds {uid} are processed within seven business days of receiving "
            f"the returned package. Funds return to the original payment method."
        ),
    )
    shipping_doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Shipping & Delivery Timelines {uid}",
        (
            f"Standard shipping {uid} takes three to five business days. Expedited "
            f"delivery options are available at checkout."
        ),
    )

    controlled_ids = {pw_doc_id, refund_doc_id, shipping_doc_id}

    query = f"I cannot log in and need to reset my password {uid}"
    data = await _search(
        client,
        test_customer_user["headers"],
        query=query,
        search_type="reranked",
        top_k=10,
    )

    assert data["search_type"] == "reranked"
    controlled_hits = [r for r in data["results"] if r["document_id"] in controlled_ids]
    assert len(controlled_hits) >= 1, "Expected at least one controlled document in reranked results"
    assert controlled_hits[0]["document_id"] == pw_doc_id, (
        f"Expected password doc to rank first among controlled docs, "
        f"got: {[r['document_id'] for r in controlled_hits]}"
    )


from unittest.mock import AsyncMock, patch
import backend.app.api.v1.knowledge as knowledge_api_module


@pytest.mark.asyncio
async def test_reranked_no_match_returns_empty(
    client: AsyncClient,
    test_admin_user: dict,
):
    """When hybrid retrieval finds zero candidate matches, reranker returns empty results."""
    with patch.object(
        knowledge_api_module.knowledge_service,
        "search_hybrid",
        new=AsyncMock(return_value=[]),
    ):
        data = await _search(
            client,
            test_admin_user["headers"],
            query="unmatched query topic",
            search_type="reranked",
            top_k=5,
        )

        assert data["search_type"] == "reranked"
        assert data["total_results"] == 0
        assert data["results"] == []


@pytest.mark.asyncio
async def test_reranked_top_k_bounds_results(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Reranked results count is strictly bounded by top_k."""
    uid = uuid.uuid4().hex[:8]
    # Ingest 3 chunks matching the same topic
    for i in range(3):
        await _ingest_raw(
            client,
            test_admin_user["headers"],
            f"Topic Guide {i} {uid}",
            f"Guidance on ticket escalation {uid} for level {i} support technicians.",
        )

    data = await _search(
        client,
        test_admin_user["headers"],
        query=f"ticket escalation {uid}",
        search_type="reranked",
        top_k=2,
    )

    assert len(data["results"]) <= 2


@pytest.mark.asyncio
async def test_reranked_all_roles_can_search(
    client: AsyncClient,
    test_admin_user: dict,
    test_agent_user: dict,
    test_customer_user: dict,
):
    """All authenticated user roles can perform reranked searches."""
    uid = uuid.uuid4().hex[:8]
    await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Universal FAQ {uid}",
        f"How to contact live support {uid} by dialing customer care numbers.",
    )

    for role_user in [test_admin_user, test_agent_user, test_customer_user]:
        data = await _search(
            client,
            role_user["headers"],
            query=f"contact live support {uid}",
            search_type="reranked",
            top_k=3,
        )
        assert data["search_type"] == "reranked"
        assert data["total_results"] >= 1


@pytest.mark.asyncio
async def test_reranked_unauthenticated_returns_401(client: AsyncClient):
    """Unauthenticated reranked search requests are rejected with 401."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "password recovery", "search_type": "reranked"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reranked_validation_empty_query_rejected(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Empty or too short query is rejected with 422 Unprocessable Entity."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "   ", "search_type": "reranked"},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_backward_compat_all_search_modes_coexist(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Verify all four search modes (vector, full_text, hybrid, reranked) coexist cleanly."""
    uid = uuid.uuid4().hex[:8]
    await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Multi-mode Doc {uid}",
        f"Operational guidelines for service availability {uid} and uptime monitoring.",
    )

    query = f"service availability {uid}"

    # 1. Default (omitted search_type) defaults to vector
    resp_default = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp_default.status_code == 200
    assert resp_default.json()["search_type"] == "vector"

    # 2. Explicit vector
    resp_vec = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "search_type": "vector", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp_vec.status_code == 200
    assert resp_vec.json()["search_type"] == "vector"
    for r in resp_vec.json()["results"]:
        assert r["rerank_score"] is None
        assert r["rrf_score"] is None

    # 3. Explicit full_text
    resp_fts = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "search_type": "full_text", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp_fts.status_code == 200
    assert resp_fts.json()["search_type"] == "full_text"
    for r in resp_fts.json()["results"]:
        assert r["rerank_score"] is None
        assert r["rrf_score"] is None

    # 4. Explicit hybrid
    resp_hyb = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "search_type": "hybrid", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp_hyb.status_code == 200
    assert resp_hyb.json()["search_type"] == "hybrid"
    for r in resp_hyb.json()["results"]:
        assert r["rerank_score"] is None

    # 5. Explicit reranked
    resp_rr = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "search_type": "reranked", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp_rr.status_code == 200
    assert resp_rr.json()["search_type"] == "reranked"
    for r in resp_rr.json()["results"]:
        assert r["rerank_score"] is not None
        assert r["score"] == r["rerank_score"]
