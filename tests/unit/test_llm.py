"""Unit tests for LLM client abstractions, Groq service, and mock service."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.app.services.llm import (
    BaseLLMService,
    GroqLLMService,
    MockLLMService,
    get_llm_service,
    set_llm_service,
)


@pytest.mark.asyncio
async def test_mock_llm_service_default_response():
    """Verify MockLLMService returns default response and records call history."""
    mock_service = MockLLMService(default_response="Custom mock answer")
    messages = [
        {"role": "system", "content": "You are a support bot."},
        {"role": "user", "content": "How do I return an item?"},
    ]

    result = await mock_service.generate(messages, temperature=0.0, max_tokens=256)

    assert result == "Custom mock answer"
    assert len(mock_service.call_history) == 1
    call = mock_service.call_history[0]
    assert call["messages"] == messages
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 256


@pytest.mark.asyncio
async def test_groq_llm_service_missing_api_key_raises_runtime_error():
    """Verify GroqLLMService raises RuntimeError if GROQ_API_KEY is unset."""
    groq_service = GroqLLMService(api_key="", client=None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not configured"):
        await groq_service.generate([{"role": "user", "content": "Hello"}])


@pytest.mark.asyncio
async def test_groq_llm_service_with_injected_client():
    """Verify GroqLLMService delegates correctly to AsyncGroq completions API."""
    mock_client = MagicMock()
    mock_completions = MagicMock()
    mock_create = AsyncMock()

    mock_choice = MagicMock()
    mock_choice.message.content = "Grounded response from Groq LLM."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_create.return_value = mock_response

    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client.chat = mock_chat

    service = GroqLLMService(
        api_key="gsk_test_key",
        model="llama-3.3-70b-versatile",
        client=mock_client,
    )

    messages = [{"role": "user", "content": "Test prompt"}]
    answer = await service.generate(messages, temperature=0.2, max_tokens=500)

    assert answer == "Grounded response from Groq LLM."
    mock_create.assert_awaited_once_with(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.2,
        max_tokens=500,
    )


def test_get_and_set_llm_service_singleton():
    """Verify set_llm_service overrides the global singleton provider."""
    original = get_llm_service()
    mock_service = MockLLMService()

    try:
        set_llm_service(mock_service)
        assert get_llm_service() is mock_service
    finally:
        set_llm_service(original)
