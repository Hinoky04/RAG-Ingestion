"""Pure result-normalization and ranking helpers for vector retrieval."""

from __future__ import annotations

from typing import Any

from src.representation.schemas import RetrievalResult


def metadata_filter(document_type: str | None = None) -> dict[str, str] | None:
    filters: dict[str, str] = {}
    if document_type:
        filters["document_type"] = document_type
    return filters or None


def first_or_none(values: list[Any] | None, index: int) -> Any:
    if not values or index >= len(values):
        return None
    return values[index]


def distance_to_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return 1 / (1 + distance)


def section_group_key(section_path: str) -> str:
    normalized = " ".join(section_path.split()).casefold()
    normalized = normalized.split(" 路 ", 1)[0]
    normalized = normalized.split(" · ", 1)[0]
    normalized = normalized.split(" (part ", 1)[0]
    return normalized


def diversify_results(results: list[RetrievalResult], top_k: int) -> list[RetrievalResult]:
    if len(results) <= 1:
        return results

    selected: list[RetrievalResult] = []
    section_hits: dict[tuple[str, str], int] = {}

    for result in sorted(results, key=lambda item: item.score, reverse=True):
        key = (result.document_id, section_group_key(result.section_path))
        seen = section_hits.get(key, 0)
        adjusted = result.model_copy(update={"score": max(0.0, result.score - (0.05 * seen))})

        insert_at = len(selected)
        for index, existing in enumerate(selected):
            if adjusted.score > existing.score:
                insert_at = index
                break
        selected.insert(insert_at, adjusted)
        section_hits[key] = seen + 1
        if len(selected) > top_k * 2:
            selected = selected[: top_k * 2]

    return selected[:top_k]
