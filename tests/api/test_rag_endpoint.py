"""API integration tests for POST /api/v1/knowledge/ask LangGraph RAG endpoint."""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from backend.app.services.llm import MockLLMService, set_llm_service
from backend.app.services.rag_graph import INSUFFICIENT_CONTEXT_MESSAGE


@pytest.mark.asyncio
async def test_ask_knowledge_unauthenticated(client: AsyncClient):
    """Verify unauthenticated requests to /knowledge/ask return 401 Unauthorized."""
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"query": "How do I return an item?"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ask_knowledge_validation_errors(
    client: AsyncClient, test_customer_user: dict
):
    """Verify invalid payloads (missing query, too short) return 422 Unprocessable Entity."""
    headers = test_customer_user["headers"]

    # Missing query
    res1 = await client.post(
        "/api/v1/knowledge/ask",
        headers=headers,
        json={},
    )
    assert res1.status_code == 422

    # Query too short (< 2 characters)
    res2 = await client.post(
        "/api/v1/knowledge/ask",
        headers=headers,
        json={"query": "a"},
    )
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_ask_knowledge_with_context_success(
    client: AsyncClient, test_customer_user: dict
):
    """Verify grounded answer synthesis when relevant knowledge is retrieved."""
    headers = test_customer_user["headers"]
    mock_llm = MockLLMService(
        default_response="Refunds are processed within 5-7 business days."
    )
    set_llm_service(mock_llm)

    mock_chunks = [
        {
            "chunk_id": "chunk-101",
            "document_id": "doc-001",
            "document_title": "Refund Policy",
            "chunk_index": 0,
            "content": "Refunds are processed within 5-7 business days via original payment.",
            "rerank_score": 0.9412,
            "score": 0.9412,
            "metadata": {"category": "billing"},
        }
    ]

    with patch(
        "backend.app.api.v1.knowledge.knowledge_service.search_reranked",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = mock_chunks

        response = await client.post(
            "/api/v1/knowledge/ask",
            headers=headers,
            json={"query": "When will I get my refund?", "top_k": 3},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "When will I get my refund?"
        assert data["context_found"] is True
        assert data["answer"] == "Refunds are processed within 5-7 business days."
        assert len(data["sources"]) == 1
        source = data["sources"][0]
        assert source["chunk_id"] == "chunk-101"
        assert source["document_title"] == "Refund Policy"
        assert source["score"] == 0.9412
        assert source["metadata"] == {"category": "billing"}


@pytest.mark.asyncio
async def test_ask_knowledge_insufficient_context(
    client: AsyncClient, test_customer_user: dict
):
    """Verify graceful fallback notice when no relevant knowledge chunks are found."""
    headers = test_customer_user["headers"]
    mock_llm = MockLLMService(default_response="Should not be called")
    set_llm_service(mock_llm)

    with patch(
        "backend.app.api.v1.knowledge.knowledge_service.search_reranked",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = []

        response = await client.post(
            "/api/v1/knowledge/ask",
            headers=headers,
            json={"query": "What is the warranty on an alien spacecraft?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["context_found"] is False
        assert data["answer"] == INSUFFICIENT_CONTEXT_MESSAGE
        assert data["sources"] == []
        # Ensure LLM was never called
        assert len(mock_llm.call_history) == 0


@pytest.mark.asyncio
async def test_ask_knowledge_llm_unconfigured_error(
    client: AsyncClient, test_customer_user: dict
):
    """Verify 503 Service Unavailable when the LLM client encounters runtime configuration errors."""
    headers = test_customer_user["headers"]

    with patch(
        "backend.app.api.v1.knowledge.knowledge_service.search_reranked",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "document_title": "Doc",
                "chunk_index": 0,
                "content": "Valid content",
                "score": 0.8,
            }
        ]

        with patch(
            "backend.app.services.rag_graph.get_llm_service"
        ) as mock_get_llm:
            failing_llm = AsyncMock()
            failing_llm.generate.side_effect = RuntimeError(
                "GROQ_API_KEY is not configured."
            )
            mock_get_llm.return_value = failing_llm

            response = await client.post(
                "/api/v1/knowledge/ask",
                headers=headers,
                json={"query": "How do I reset my password?"},
            )

            assert response.status_code == 503
            assert "GROQ_API_KEY is not configured" in response.json()["detail"]
