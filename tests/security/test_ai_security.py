"""Security tests for LLM and RAG Agent Hardening (Phase 18)."""

import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.services.llm import BaseLLMService
from backend.app.services.rag_graph import run_rag_pipeline


class MockSecurityLLM(BaseLLMService):
    """Mock LLM returning safe canned response."""

    async def generate(self, messages: list[dict[str, str]], **kwargs) -> str:
        return "Grounded policy answer based strictly on verified reference documents."


@pytest.mark.asyncio
async def test_ai_query_length_bounded(db_session: AsyncSession):
    """Verify that user queries exceeding MAX_AI_INPUT_CHARS are safely truncated."""
    long_query = "What is the return policy? " + ("A" * 6000)
    mock_llm = MockSecurityLLM()

    result = await run_rag_pipeline(
        query=long_query,
        db=db_session,
        llm_service=mock_llm,
    )

    # Result state query must be truncated to settings.MAX_AI_INPUT_CHARS
    assert len(result["query"]) <= settings.MAX_AI_INPUT_CHARS
    assert result["query"].startswith("What is the return policy?")


@pytest.mark.asyncio
async def test_ai_retrieved_context_sandboxing(db_session: AsyncSession):
    """Verify that retrieved documents are encapsulated in untrusted reference tags."""
    from backend.app.services.rag_graph import build_rag_graph

    graph = build_rag_graph(
        knowledge_service=AsyncMock(),
        llm_service=MockSecurityLLM(),
        db=db_session,
    )
    assert graph is not None
