"""Unit tests for Phase 7 — EmbeddingService.

Tests coverage:
- Single text embedding dimension and type validation.
- Batch embedding with correct dimensions.
- Validation for empty or whitespace-only strings.
- Validation for non-string inputs.
- Empty batch handling.
- Embedding vector dimensionality mismatch detection.
- Normalization verification.
"""

from unittest.mock import MagicMock
import numpy as np
import pytest

from backend.app.services.embedding import EmbeddingService


@pytest.fixture
def mock_sentence_transformer():
    """Mock SentenceTransformer that returns deterministic normalized vectors."""
    mock_model = MagicMock()

    def fake_encode(sentences, convert_to_numpy=True, normalize_embeddings=True, **kwargs):
        dim = 384
        if isinstance(sentences, str):
            vec = np.ones(dim, dtype=np.float32)
            norm = np.linalg.norm(vec)
            return vec / norm if normalize_embeddings else vec
        
        # Batch of sentences
        batch_vecs = []
        for s in sentences:
            vec = np.ones(dim, dtype=np.float32) * (len(s) + 1.0)
            norm = np.linalg.norm(vec)
            batch_vecs.append(vec / norm if normalize_embeddings else vec)
        return np.array(batch_vecs, dtype=np.float32)

    mock_model.encode.side_effect = fake_encode
    return mock_model


def test_embed_single_text_success(mock_sentence_transformer):
    """Verify single string produces expected 384-dimensional float vector."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    vector = service.embed_text("How do I return a purchased product?")
    assert isinstance(vector, list)
    assert len(vector) == 384
    assert all(isinstance(x, float) for x in vector)
    # Check normalized (L2 norm ~ 1.0)
    norm = np.linalg.norm(np.array(vector))
    assert pytest.approx(norm, rel=1e-4) == 1.0


def test_embed_batch_success(mock_sentence_transformer):
    """Verify batch processing produces list of 384-dimensional float vectors."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    texts = [
        "Refund policy and timeline details.",
        "How to cancel pending orders.",
        "Updating delivery address after purchase.",
    ]
    vectors = service.embed_batch(texts)
    assert len(vectors) == 3
    for v in vectors:
        assert isinstance(v, list)
        assert len(v) == 384
        assert all(isinstance(x, float) for x in v)
        norm = np.linalg.norm(np.array(v))
        assert pytest.approx(norm, rel=1e-4) == 1.0


def test_embed_empty_batch(mock_sentence_transformer):
    """Empty list returns empty results without invoking model."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    assert service.embed_batch([]) == []
    mock_sentence_transformer.encode.assert_not_called()


@pytest.mark.parametrize("empty_input", ["", "   ", "\n\t  \n"])
def test_embed_text_empty_input_raises_value_error(mock_sentence_transformer, empty_input):
    """Empty or whitespace-only string raises ValueError."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    with pytest.raises(ValueError, match="Cannot generate embedding for empty or whitespace-only text"):
        service.embed_text(empty_input)


def test_embed_text_non_string_raises_type_error(mock_sentence_transformer):
    """Non-string input raises TypeError."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    with pytest.raises(TypeError, match="Text input must be a string"):
        service.embed_text(12345)  # type: ignore


def test_embed_batch_with_invalid_element_raises(mock_sentence_transformer):
    """Batch containing invalid or empty elements raises appropriate exception."""
    service = EmbeddingService(dimension=384)
    service._model = mock_sentence_transformer

    with pytest.raises(ValueError, match="empty or whitespace-only"):
        service.embed_batch(["Valid text", "   ", "Another valid text"])

    with pytest.raises(TypeError, match="must be a string"):
        service.embed_batch(["Valid text", None])  # type: ignore


def test_dimension_mismatch_raises_value_error():
    """If the underlying model returns unexpected dimensions, ValueError is raised."""
    mock_model = MagicMock()
    # Return 128 dimensions instead of expected 384
    mock_model.encode.return_value = np.zeros(128, dtype=np.float32)

    service = EmbeddingService(dimension=384)
    service._model = mock_model

    with pytest.raises(ValueError, match="Generated embedding dimension 128 does not match expected 384"):
        service.embed_text("Sample query")
