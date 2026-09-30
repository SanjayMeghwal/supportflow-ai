"""LLM service abstraction supporting Groq and swappable local/mock providers with token tracking."""

from abc import ABC, abstractmethod
import time
from typing import Any, Optional

from groq import AsyncGroq

from backend.app.core.config import settings
from backend.app.services.llm_analytics import estimate_tokens, llm_analytics_service


class BaseLLMService(ABC):
    """Abstract base class defining the standardized LLM client interface."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        operation: str = "rag_synthesis",
    ) -> str:
        """Generate a completion for the provided chat messages.

        Parameters
        ----------
        messages : list[dict[str, str]]
            List of message dicts with 'role' and 'content' keys.
        temperature : float, optional
            Sampling temperature (0.0 for deterministic factual answers).
        max_tokens : int, optional
            Maximum tokens to generate.
        operation : str, optional
            Operation name for analytics categorization.

        Returns
        -------
        str
            The generated response text.
        """
        pass


class GroqLLMService(BaseLLMService):
    """Groq API client implementing BaseLLMService for high-throughput inference."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[AsyncGroq] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self._client = client

    def _get_client(self) -> AsyncGroq:
        if self._client is not None:
            return self._client

        if not self.api_key or not self.api_key.strip():
            raise RuntimeError(
                "GROQ_API_KEY is not configured. Set GROQ_API_KEY in the environment or .env file."
            )
        self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        operation: str = "rag_synthesis",
    ) -> str:
        """Generate response via Groq chat completion API with latency and token telemetry."""
        client = self._get_client()
        start_time = time.perf_counter()

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000.0)
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract token telemetry from provider response
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                completion_tokens = getattr(usage, "completion_tokens", None)
                total_tokens = getattr(usage, "total_tokens", None)
                is_estimated = False
            else:
                prompt_text = " ".join(m.get("content", "") for m in messages)
                prompt_tokens = estimate_tokens(prompt_text)
                completion_tokens = estimate_tokens(content)
                total_tokens = prompt_tokens + completion_tokens
                is_estimated = True

            llm_analytics_service.record_call(
                model=self.model,
                provider="groq",
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_estimated=is_estimated,
                latency_ms=duration_ms,
                success=True,
            )

            return content

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000.0)
            llm_analytics_service.record_call(
                model=self.model,
                provider="groq",
                operation=operation,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                is_estimated=False,
                latency_ms=duration_ms,
                success=False,
                error_type=exc.__class__.__name__,
            )
            raise


class MockLLMService(BaseLLMService):
    """Mock LLM service for testing and offline development."""

    def __init__(
        self,
        default_response: str = "This is a deterministic mock response based strictly on the retrieved context.",
        responses: Optional[list[str]] = None,
    ) -> None:
        self.default_response = default_response
        self._responses: list[str] = list(responses) if responses else []
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        operation: str = "mock_synthesis",
    ) -> str:
        start_time = time.perf_counter()
        self.call_history.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._responses:
            res = self._responses.pop(0)
        else:
            res = self.default_response

        duration_ms = max(1, int((time.perf_counter() - start_time) * 1000.0))
        prompt_text = " ".join(m.get("content", "") for m in messages)
        prompt_tokens = estimate_tokens(prompt_text)
        completion_tokens = estimate_tokens(res)
        total_tokens = prompt_tokens + completion_tokens

        llm_analytics_service.record_call(
            model="mock-deterministic",
            provider="mock",
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_estimated=True,
            latency_ms=duration_ms,
            success=True,
        )

        return res


_llm_service_instance: Optional[BaseLLMService] = None


def get_llm_service() -> BaseLLMService:
    """Return the global singleton LLM service instance."""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = GroqLLMService()
    return _llm_service_instance


def set_llm_service(service: BaseLLMService) -> None:
    """Override the global LLM service instance (primarily used for test fixtures)."""
    global _llm_service_instance
    _llm_service_instance = service
