"""Validation summaries and chunk records for the workspace."""

from __future__ import annotations

from sourcecode.pipeline.ingest_service import IngestionOutcome


def build_validation_report(outcome: IngestionOutcome) -> tuple[str, dict, list[dict]]:
    """Make status and numbers shown on review page."""
    # Missing artifact is error. Short or repeated chunk is warning only.

    block_count = len(outcome.document.blocks)
    chunk_count = len(outcome.chunks)
    artifact_presence = {
        "document_json": outcome.artifacts.document_path is not None,
        "markdown": outcome.artifacts.markdown_path is not None,
        "chunks": outcome.artifacts.chunk_path is not None,
    }
    summary = {
        "block_count": block_count,
        "chunk_count": chunk_count,
        "parser_name": outcome.parser_name,
        "parser_version": outcome.parser_version,
        "artifact_presence": artifact_presence,
    }
    events: list[dict] = []

    if block_count == 0:
        events.append(
            {
                "severity": "warning",
                "event_code": "NO_BLOCKS",
                "event_message": "Parser completed, but no structured blocks were produced.",
                "event_meta": {"block_count": block_count},
            }
        )
    if chunk_count == 0:
        events.append(
            {
                "severity": "warning",
                "event_code": "NO_CHUNKS",
                "event_message": "Parser completed, but no retrieval chunks were produced.",
                "event_meta": {"chunk_count": chunk_count},
            }
        )
    if not artifact_presence["chunks"]:
        events.append(
            {
                "severity": "warning",
                "event_code": "MISSING_CHUNK_ARTIFACT",
                "event_message": "No chunk artifact path was recorded for this run.",
                "event_meta": artifact_presence,
            }
        )

    status = "review_ready" if block_count > 0 and chunk_count > 0 and artifact_presence["chunks"] else "low_confidence"
    summary["automation_status"] = status
    return status, summary, events


def chunk_records_for_workspace(outcome: IngestionOutcome) -> list[dict]:
    """Build light-weight database records while retaining full text in artifacts."""

    return [
        {
            "chunk_id": chunk.chunk_id,
            "chunk_index": index,
            "section_path": chunk.section_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text_preview": chunk.text[:500],
            "source_block_ids": chunk.source_block_ids,
            "metadata_json": chunk.metadata,
        }
        for index, chunk in enumerate(outcome.chunks, start=1)
    ]
