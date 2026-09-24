"""Local text embedding service using sentence-transformers.

Provides dense vector embeddings for RAG retrieval and knowledge base indexing.
Design guarantees:
- Completely open-source & local (zero external API calls or costs).
- Lazy singleton model initialization (avoids reloading weights per request).
- Normalized embeddings (unit length for optimal cosine similarity).
- Input validation (rejects empty/whitespace text, ensures strict dimensionality).
- Pluggable/mockable architecture for testing.
"""

from typing import Optional
from sentence_transformers import SentenceTransformer

from backend.app.core.config import settings


class EmbeddingService:
    """Manages local sentence-transformer models for dense vector generation."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        dimension: Optional[int] = None,
    ) -> None:
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.dimension = dimension or settings.EMBEDDING_DIMENSION
        self._model: Optional[SentenceTransformer] = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loader for the SentenceTransformer model."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Generate a dense normalized vector embedding for a single text string."""
        if not isinstance(text, str):
            raise TypeError("Text input must be a string.")
        stripped = text.strip()
        if not stripped:
            raise ValueError("Cannot generate embedding for empty or whitespace-only text.")

        vector = self.model.encode(
            stripped,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        embedding_list = vector.tolist()

        if len(embedding_list) != self.dimension:
            raise ValueError(
                f"Generated embedding dimension {len(embedding_list)} does not match expected {self.dimension}."
            )
        return embedding_list

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate dense normalized vector embeddings for a batch of text strings."""
        if not texts:
            return []

        cleaned_texts: list[str] = []
        for i, text in enumerate(texts):
            if not isinstance(text, str):
                raise TypeError(f"Text at index {i} must be a string, got {type(text).__name__}.")
            stripped = text.strip()
            if not stripped:
                raise ValueError(f"Text at index {i} is empty or whitespace-only.")
            cleaned_texts.append(stripped)

        vectors = self.model.encode(
            cleaned_texts,
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        results = vectors.tolist()

        for i, emb in enumerate(results):
            if len(emb) != self.dimension:
                raise ValueError(
                    f"Generated embedding at index {i} has dimension {len(emb)}, expected {self.dimension}."
                )
        return results


# Global singleton instance
_embedding_service_instance: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Dependency / accessor for the singleton EmbeddingService."""
    global _embedding_service_instance
    if _embedding_service_instance is None:
        _embedding_service_instance = EmbeddingService()
    return _embedding_service_instance
