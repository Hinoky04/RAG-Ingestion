"""Quality checks for retrieval chunks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from sourcecode.representation.schemas import DocumentChunk


MIN_RETRIEVAL_WORDS = 25


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(frozen=True)
class ChunkQualityReport:
    total_chunks: int
    short_chunks: int
    duplicate_chunks: int
    chunks_without_provenance: int
    chunks_without_locator: int


def assess_chunks(chunks: list[DocumentChunk]) -> ChunkQualityReport:
    """Report structural warning signals without treating them as relevance scores."""
    text_counts = Counter(normalized_text(chunk.text) for chunk in chunks)
    return ChunkQualityReport(
        total_chunks=len(chunks),
        short_chunks=sum(len(chunk.text.split()) < MIN_RETRIEVAL_WORDS for chunk in chunks),
        duplicate_chunks=sum(count - 1 for count in text_counts.values() if count > 1),
        chunks_without_provenance=sum(not chunk.source_block_ids for chunk in chunks),
        chunks_without_locator=sum(chunk.page_start is None and not chunk.metadata.get("source_anchor") for chunk in chunks),
    )
