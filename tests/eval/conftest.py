"""Phase 15 — eval/ conftest: lightweight fixtures used by AI evaluation benchmarks.

No database interaction is required here. These fixtures provide:
- A pre-loaded EvaluationDataset from the bundled benchmark JSON.
- A configured EvaluationRunner with MockLLMService (deterministic, no API key).
- Per-category sample subsets for isolated metric assertions.
"""

import pytest
import pytest_asyncio

from backend.app.evaluation.dataset import EvaluationDataset
from backend.app.evaluation.runner import EvaluationRunner
from backend.app.evaluation.schemas import EvaluationSample
from backend.app.services.llm import MockLLMService


@pytest.fixture(scope="session")
def benchmark_dataset() -> EvaluationDataset:
    """Load the bundled benchmark JSON dataset once per session."""
    return EvaluationDataset.load_from_json()


@pytest.fixture(scope="session")
def mock_llm() -> MockLLMService:
    """Deterministic MockLLMService that echoes reference answers (no API key)."""
    return MockLLMService()


@pytest.fixture(scope="session")
def offline_runner(benchmark_dataset: EvaluationDataset, mock_llm: MockLLMService) -> EvaluationRunner:
    """Pre-configured EvaluationRunner for offline deterministic benchmarks."""
    return EvaluationRunner(dataset=benchmark_dataset, llm_service=mock_llm, top_k=5)


@pytest.fixture(scope="session")
def answerable_samples(benchmark_dataset: EvaluationDataset) -> list[EvaluationSample]:
    """Return only the answerable (positive) samples from the dataset."""
    return [s for s in benchmark_dataset if s.is_answerable]


@pytest.fixture(scope="session")
def unanswerable_samples(benchmark_dataset: EvaluationDataset) -> list[EvaluationSample]:
    """Return only the unanswerable (negative/out-of-domain) samples."""
    return [s for s in benchmark_dataset if not s.is_answerable]
