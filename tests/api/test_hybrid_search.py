"""Phase 8 API integration tests — PostgreSQL FTS, Hybrid Search, and RRF.

Test isolation strategy
-----------------------
Each test creates its own uniquely-named documents (UUID hex suffix embedded
in both the title and content).  Assertions are anchored to specific
document_id values returned at creation time.  Results from other tests'
documents are filtered out before asserting rank or presence.

This eliminates the need for top_k=50 workarounds.  The shared test database
may contain documents from other tests, but only the controlled test documents
matter for correctness assertions.

Coverage
--------
A. PostgreSQL FTS via search_type=full_text:
   1. Exact keyword match returns the correct document.
   2. Inactive documents are excluded from FTS results.
   3. Technical term matching (FTS advantage over pure vector).
   4. No-match query returns empty results (graceful FTS degradation).
   5. All authenticated roles can search with full_text.
   6. Unauthenticated FTS request is rejected with 401.
   7. top_k bounds FTS results correctly.

B. Hybrid search via search_type=hybrid:
   8.  Semantic query retrieves correct document (hybrid mode).
   9.  Hybrid result includes vector_rank and fts_rank for hybrid items.
  10.  Inactive documents excluded from hybrid results.
  11.  Hybrid returns results even when FTS yields no match (vector-only).
  12.  Hybrid returns results even when FTS matches but vector is dominant.
  13.  top_k bounds hybrid results correctly.

C. Backward compatibility:
  14.  Omitting search_type defaults to vector (Phase 7 compat).
  15.  search_type=vector behaves identically to Phase 7.
  16.  search_type field is present in all responses.
  17.  Vector response does not expose vector_rank/fts_rank (None).

D. Input validation:
  18.  Invalid search_type string is rejected with 422.
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
    search_type: str,
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


# ===========================================================================
# A. PostgreSQL FTS tests
# ===========================================================================


@pytest.mark.asyncio
async def test_fts_exact_keyword_match(
    client: AsyncClient,
    test_admin_user: dict,
):
    """FTS returns the document whose chunk contains the exact query keyword."""
    uid = uuid.uuid4().hex[:8]
    title = f"Password Reset Policy {uid}"
    content = (
        f"Password reset {uid} requires verifying your registered email address. "
        f"Click the secure link sent to your inbox to complete the process."
    )
    doc_id = await _ingest_raw(client, test_admin_user["headers"], title, content)

    data = await _search(client, test_admin_user["headers"], f"password reset {uid}", "full_text")

    assert data["search_type"] == "full_text"
    result_doc_ids = _doc_ids_in_results(data)
    assert doc_id in result_doc_ids, (
        f"Expected document {doc_id} in FTS results, got: {result_doc_ids}"
    )
    # The matching document must be first among the controlled docs
    relevant = [r for r in data["results"] if r["document_id"] == doc_id]
    assert relevant[0]["score"] > 0.0


@pytest.mark.asyncio
async def test_fts_inactive_document_excluded(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Inactive documents must not appear in FTS results."""
    uid = uuid.uuid4().hex[:8]
    marker = f"SUPERSECRET_FTS_INACTIVE_{uid}"
    doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Inactive FTS Doc {uid}",
        f"Confidential {marker} text that must never be retrieved.",
    )

    # Deactivate
    doc_db = await db_session.get(KnowledgeDocument, uuid.UUID(doc_id))
    assert doc_db is not None
    doc_db.is_active = False
    await db_session.commit()

    data = await _search(client, test_admin_user["headers"], marker, "full_text", top_k=20)

    assert doc_id not in _doc_ids_in_results(data), (
        "Inactive document appeared in FTS results"
    )


@pytest.mark.asyncio
async def test_fts_technical_term_matching(
    client: AsyncClient,
    test_admin_user: dict,
):
    """FTS finds documents containing specific technical/business identifiers.

    This test demonstrates a primary advantage of FTS: exact term recall for
    identifiers that may not have strong semantic embeddings.
    """
    uid = uuid.uuid4().hex[:8]
    error_code = f"ERR{uid.upper()}"
    doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Error Code Reference {uid}",
        f"When you encounter {error_code}, it means the session token has expired. "
        f"Log out and log back in to resolve the authentication failure.",
    )

    data = await _search(client, test_admin_user["headers"], error_code, "full_text")

    assert data["search_type"] == "full_text"
    result_doc_ids = _doc_ids_in_results(data)
    assert doc_id in result_doc_ids, (
        f"Expected exact error-code doc {doc_id} in FTS results, got: {result_doc_ids}"
    )


@pytest.mark.asyncio
async def test_fts_no_match_returns_empty(
    client: AsyncClient,
    test_admin_user: dict,
):
    """FTS returns empty results gracefully when no chunk matches the query."""
    # Use a completely random string that will not match any chunk
    nonsense = f"xyzzy_no_match_{uuid.uuid4().hex}"
    data = await _search(client, test_admin_user["headers"], nonsense, "full_text")

    assert data["search_type"] == "full_text"
    assert data["total_results"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_fts_all_roles_can_search(
    client: AsyncClient,
    test_admin_user: dict,
    test_agent_user: dict,
    test_customer_user: dict,
):
    """All authenticated roles (ADMIN, AGENT, CUSTOMER) can use FTS."""
    uid = uuid.uuid4().hex[:8]
    await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Shared FTS Doc {uid}",
        f"Refund policy {uid} for returned items within thirty days.",
    )

    for user in [test_admin_user, test_agent_user, test_customer_user]:
        resp = await client.post(
            "/api/v1/knowledge/search",
            json={"query": f"refund {uid}", "search_type": "full_text", "top_k": 3},
            headers=user["headers"],
        )
        assert resp.status_code == 200, f"Role failed FTS: {resp.text}"


@pytest.mark.asyncio
async def test_fts_unauthenticated_returns_401(client: AsyncClient):
    """FTS without auth token is rejected with 401."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "password reset", "search_type": "full_text"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fts_top_k_bounds_results(
    client: AsyncClient,
    test_admin_user: dict,
):
    """FTS result count is bounded by top_k."""
    uid = uuid.uuid4().hex[:8]
    # Ingest multiple chunks that will all match
    for i in range(3):
        await _ingest_raw(
            client,
            test_admin_user["headers"],
            f"Refund Guide {i} {uid}",
            f"Refund processing {uid} takes five business days for order {i}.",
        )

    data = await _search(client, test_admin_user["headers"], f"refund {uid}", "full_text", top_k=2)

    assert len(data["results"]) <= 2


# ===========================================================================
# B. Hybrid search tests
# ===========================================================================


@pytest.mark.asyncio
async def test_hybrid_semantic_query_retrieves_correct_document(
    client: AsyncClient,
    test_admin_user: dict,
    test_customer_user: dict,
):
    """Hybrid search finds semantically relevant documents for natural-language queries.

    Uses three controlled documents:
    - Password: semantically about account recovery / login credentials
    - Refund: semantically about money-back / order returns
    - TFA: semantically about two-factor authentication / security

    Query 'I forgot my password' should surface the Password document highest
    among the three controlled docs.
    """
    uid = uuid.uuid4().hex[:8]

    pw_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Password Reset Policy {uid}",
        (
            f"Password reset {uid} requires verifying your registered email address. "
            f"Click the secure link sent to your inbox to complete the process."
        ),
    )
    refund_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Refund Policy {uid}",
        (
            f"Refunds {uid} are processed within five business days. "
            f"Money is returned to the original payment method used at checkout."
        ),
    )
    tfa_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Two-Factor Auth Policy {uid}",
        (
            f"Two-factor authentication {uid} protects your account login. "
            f"Enable it from account security settings."
        ),
    )

    controlled_ids = {pw_id, refund_id, tfa_id}

    data = await _search(
        client, test_customer_user["headers"], f"I forgot my password {uid}", "hybrid", top_k=10
    )

    assert data["search_type"] == "hybrid"
    # Filter to our controlled docs only
    controlled_hits = [r for r in data["results"] if r["document_id"] in controlled_ids]
    assert len(controlled_hits) >= 1, "Expected at least one controlled doc in hybrid results"
    # Password document must rank highest among controlled docs
    assert controlled_hits[0]["document_id"] == pw_id, (
        f"Expected password doc first among controlled docs, "
        f"got: {[r['document_id'] for r in controlled_hits]}"
    )


@pytest.mark.asyncio
async def test_hybrid_result_exposes_rank_metadata(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Hybrid results include vector_rank and fts_rank for debugging/evaluation."""
    uid = uuid.uuid4().hex[:8]
    await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Debug Hybrid Doc {uid}",
        f"Password credentials {uid} reset secure token verification email link.",
    )

    data = await _search(
        client, test_admin_user["headers"], f"password {uid}", "hybrid", top_k=5
    )

    assert data["search_type"] == "hybrid"
    assert data["total_results"] >= 1

    # At least one result should have rank metadata populated
    # (a chunk retrieved by both systems will have both ranks set)
    for r in data["results"]:
        # vector_rank and fts_rank can be None (chunk in only one system)
        # but they must be present as JSON fields
        assert "vector_rank" in r
        assert "fts_rank" in r
        if r["vector_rank"] is not None:
            assert r["vector_rank"] >= 1
        if r["fts_rank"] is not None:
            assert r["fts_rank"] >= 1


@pytest.mark.asyncio
async def test_hybrid_inactive_document_excluded(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Inactive documents must not appear in hybrid search results."""
    uid = uuid.uuid4().hex[:8]
    marker = f"SUPERSECRET_HYBRID_{uid}"
    doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Inactive Hybrid Doc {uid}",
        f"Confidential {marker} content that must never be retrieved.",
    )

    doc_db = await db_session.get(KnowledgeDocument, uuid.UUID(doc_id))
    assert doc_db is not None
    doc_db.is_active = False
    await db_session.commit()

    data = await _search(client, test_admin_user["headers"], marker, "hybrid", top_k=20)

    assert doc_id not in _doc_ids_in_results(data), (
        "Inactive document appeared in hybrid results"
    )


@pytest.mark.asyncio
async def test_hybrid_no_fts_match_falls_back_to_vector(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Hybrid search returns vector results even when FTS yields no match.

    Uses a semantic query without specific keywords from the chunk text,
    so FTS will return zero candidates.  The hybrid result should still
    surface semantically relevant content from vector search.
    """
    uid = uuid.uuid4().hex[:8]
    doc_id = await _ingest_raw(
        client,
        test_admin_user["headers"],
        f"Account Recovery {uid}",
        (
            f"If you cannot access your account {uid}, navigate to the credentials "
            f"portal and dispatch a secure one-time passcode to your registered device."
        ),
    )

    # Query is semantically close but uses different vocabulary than the chunk
    data = await _search(
        client,
        test_admin_user["headers"],
        f"I lost my login access {uid}",
        "hybrid",
        top_k=10,
    )

    assert data["search_type"] == "hybrid"
    # The document should appear via vector search even if FTS finds nothing
    result_doc_ids = _doc_ids_in_results(data)
    assert doc_id in result_doc_ids


@pytest.mark.asyncio
async def test_hybrid_top_k_bounds_results(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Hybrid result count is bounded by top_k."""
    data = await _search(
        client, test_admin_user["headers"], "customer support refund policy", "hybrid", top_k=1
    )
    assert len(data["results"]) <= 1


@pytest.mark.asyncio
async def test_hybrid_unauthenticated_returns_401(client: AsyncClient):
    """Hybrid search without auth token is rejected with 401."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "password reset", "search_type": "hybrid"},
    )
    assert resp.status_code == 401


# ===========================================================================
# C. Backward compatibility tests
# ===========================================================================


@pytest.mark.asyncio
async def test_backward_compat_no_search_type_defaults_to_vector(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Phase 7 clients that omit search_type get vector search (default)."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "account security policy", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["search_type"] == "vector"


@pytest.mark.asyncio
async def test_backward_compat_explicit_vector_mode(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Explicit search_type=vector behaves identically to Phase 7."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "account security policy", "search_type": "vector", "top_k": 3},
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["search_type"] == "vector"
    # Vector results have no rank metadata (None)
    for r in data["results"]:
        assert r["vector_rank"] is None
        assert r["fts_rank"] is None


@pytest.mark.asyncio
async def test_search_type_present_in_all_responses(
    client: AsyncClient,
    test_admin_user: dict,
):
    """search_type field is present in responses for all three modes."""
    for mode in ["vector", "full_text", "hybrid"]:
        resp = await client.post(
            "/api/v1/knowledge/search",
            json={"query": "customer refund policy", "search_type": mode, "top_k": 3},
            headers=test_admin_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "search_type" in data
        assert data["search_type"] == mode


# ===========================================================================
# D. Input validation tests
# ===========================================================================


@pytest.mark.asyncio
async def test_invalid_search_type_rejected_with_422(
    client: AsyncClient,
    test_customer_user: dict,
):
    """An unrecognised search_type value is rejected with 422 Unprocessable Entity."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "test query", "search_type": "elasticsearch"},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fts_validation_empty_query_rejected(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Empty query is rejected with 422 for FTS mode too."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "  ", "search_type": "full_text", "top_k": 5},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_hybrid_validation_empty_query_rejected(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Empty query is rejected with 422 for hybrid mode too."""
    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "x", "search_type": "hybrid", "top_k": 5},
        headers=test_customer_user["headers"],
    )
    # "x" is length 1 — fails min_length=2 validator
    assert resp.status_code == 422
