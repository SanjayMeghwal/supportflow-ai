"""Dataset loader, validator, and filtering for benchmark evaluation."""

import json
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence
from pydantic import ValidationError

from backend.app.evaluation.schemas import EvaluationSample

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "data" / "benchmark_dataset.json"


class DatasetError(Exception):
    """Exception raised when a benchmark dataset cannot be loaded or validated."""
    pass


class EvaluationDataset:
    """Manages loading, validation, and filtering of evaluation benchmark datasets."""

    def __init__(self, samples: Sequence[EvaluationSample], source_path: Optional[Path] = None) -> None:
        self._samples = list(samples)
        self._source_path = source_path
        self._sample_index: dict[str, EvaluationSample] = {}

        # Validate unique sample IDs
        for sample in self._samples:
            if sample.id in self._sample_index:
                raise DatasetError(f"Duplicate sample ID detected: '{sample.id}'")
            self._sample_index[sample.id] = sample

    @property
    def samples(self) -> list[EvaluationSample]:
        """Return the underlying list of valid samples."""
        return list(self._samples)

    @property
    def source_path(self) -> Optional[Path]:
        """File path from which dataset was loaded, if any."""
        return self._source_path

    def __len__(self) -> int:
        return len(self._samples)

    def __iter__(self) -> Iterator[EvaluationSample]:
        return iter(self._samples)

    def get_sample(self, sample_id: str) -> Optional[EvaluationSample]:
        """Retrieve a specific sample by unique ID."""
        return self._sample_index.get(sample_id)

    def categories(self) -> list[str]:
        """List distinct categories present in this dataset."""
        return sorted(list({s.category for s in self._samples if s.category}))

    def filter(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        is_answerable: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> "EvaluationDataset":
        """Return a filtered copy of the benchmark dataset."""
        filtered = self._samples

        if category is not None:
            filtered = [s for s in filtered if s.category.lower() == category.lower()]

        if difficulty is not None:
            filtered = [s for s in filtered if s.difficulty.lower() == difficulty.lower()]

        if is_answerable is not None:
            filtered = [s for s in filtered if s.is_answerable == is_answerable]

        if limit is not None and limit > 0:
            filtered = filtered[:limit]

        return EvaluationDataset(filtered, source_path=self._source_path)

    @classmethod
    def load_from_json(cls, path_or_str: str | Path | None = None) -> "EvaluationDataset":
        """Load and validate benchmark dataset from a JSON file.

        Parameters
        ----------
        path_or_str : str | Path | None
            File path to JSON dataset. Defaults to built-in benchmark dataset.

        Raises
        ------
        DatasetError
            If file is missing, contains invalid JSON, or schema validation fails.
        """
        path = Path(path_or_str) if path_or_str is not None else DEFAULT_DATASET_PATH

        if not path.exists():
            raise DatasetError(f"Benchmark dataset file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"Malformed JSON in dataset file {path}: {exc}") from exc
        except Exception as exc:
            raise DatasetError(f"Failed to read dataset file {path}: {exc}") from exc

        if not isinstance(raw_data, list):
            raise DatasetError(f"Dataset root must be a JSON array, got {type(raw_data).__name__}")

        if len(raw_data) == 0:
            raise DatasetError(f"Dataset at {path} contains zero samples")

        samples: list[EvaluationSample] = []
        for idx, item in enumerate(raw_data):
            if not isinstance(item, dict):
                raise DatasetError(f"Sample at index {idx} is not a JSON object")
            try:
                sample = EvaluationSample.model_validate(item)
                samples.append(sample)
            except ValidationError as val_err:
                raise DatasetError(
                    f"Sample validation failed at index {idx} (id={item.get('id', 'unknown')}): {val_err}"
                ) from val_err

        return cls(samples, source_path=path)

    @classmethod
    def load_from_dict_list(cls, data: list[dict[str, Any]]) -> "EvaluationDataset":
        """Create a dataset directly from a list of dictionaries (useful in tests)."""
        if not data:
            raise DatasetError("Dataset dictionary list is empty")

        samples: list[EvaluationSample] = []
        for idx, item in enumerate(data):
            try:
                samples.append(EvaluationSample.model_validate(item))
            except ValidationError as exc:
                raise DatasetError(f"Invalid sample at index {idx}: {exc}") from exc

        return cls(samples)
