"""LLM service abstraction supporting Groq and swappable local/mock providers."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from groq import AsyncGroq

from backend.app.core.config import settings


class BaseLLMService(ABC):
    """Abstract base class defining the standardized LLM client interface."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
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
    ) -> str:
        """Generate response via Groq chat completion API."""
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        return choice.message.content or ""


class MockLLMService(BaseLLMService):
    """Mock LLM service for testing and offline development.

    Accepts either a single ``default_response`` string (returned on every call)
    or a ``responses`` list (each call pops the next item; falls back to
    ``default_response`` when the list is exhausted).  Both arguments are
    optional and can be combined.
    """

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
    ) -> str:
        self.call_history.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return self.default_response


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
