"""Deterministic recursive text chunking engine for Knowledge Base RAG ingestion."""

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class TextChunk:
    """Represents an extracted text chunk with associated positional metadata."""

    chunk_index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RecursiveTextChunker:
    """Recursively splits text into semantic chunks respecting natural text boundaries.

    Hierarchy of separators:
      1. Paragraph breaks ("\n\n")
      2. Line breaks ("\n")
      3. Sentence endings (". ", "? ", "! ")
      4. Clause boundaries ("; ", ", ")
      5. Word spaces (" ")
      6. Raw character slicing ("")

    Guarantees:
      - Deterministic: Same input yields identical chunks.
      - Chunks respect maximum size where possible without truncating mid-word
        (unless a single word exceeds chunk_size).
      - Successive chunks overlap by ~chunk_overlap characters for semantic continuity.
    """

    DEFAULT_SEPARATORS: list[str] = [
        "\n\n",
        "\n",
        ". ",
        "? ",
        "! ",
        "; ",
        ", ",
        " ",
        "",
    ]

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

    def split_text(
        self,
        text: str,
        document_metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """Split a source text into sequential TextChunk instances."""
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized_text:
            return []

        doc_meta = document_metadata or {}
        raw_chunks = self._recursive_split(normalized_text, self.separators)

        result: list[TextChunk] = []
        for idx, chunk_str in enumerate(raw_chunks):
            cleaned = chunk_str.strip()
            if not cleaned:
                continue

            chunk_meta = {
                **doc_meta,
                "char_count": len(cleaned),
                "word_count": len(cleaned.split()),
            }
            result.append(
                TextChunk(
                    chunk_index=len(result),
                    text=cleaned,
                    metadata=chunk_meta,
                )
            )

        return result

    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        """Split text using the highest-priority separator that matches."""
        if len(text) <= self.chunk_size:
            return [text]

        separator = ""
        new_separators: list[str] = []
        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1 :]
                break

        # Split text by separator
        if separator != "":
            splits = text.split(separator)
        else:
            # Character-level slicing fallback
            splits = [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        # Recombine splits greedily into chunks of at most chunk_size
        good_splits: list[str] = []
        for s in splits:
            if separator and s:
                part = s if s.endswith(separator) else s + separator
            else:
                part = s

            if len(part) > self.chunk_size and new_separators:
                # Part is still too large: recursively split using remaining separators
                sub_splits = self._recursive_split(part, new_separators)
                good_splits.extend(sub_splits)
            elif part:
                good_splits.append(part)

        return self._merge_splits(good_splits, separator)

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        """Merge smaller fragments into chunks up to chunk_size with chunk_overlap."""
        docs: list[str] = []
        current_doc: list[str] = []
        total = 0

        for piece in splits:
            piece_len = len(piece)
            if total + piece_len > self.chunk_size and current_doc:
                doc = "".join(current_doc).strip()
                if doc:
                    docs.append(doc)

                # Keep trailing pieces for overlap
                while total > self.chunk_overlap and current_doc:
                    removed = current_doc.pop(0)
                    total -= len(removed)

            current_doc.append(piece)
            total += piece_len

        if current_doc:
            doc = "".join(current_doc).strip()
            if doc:
                docs.append(doc)

        return docs
