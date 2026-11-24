"""Writers for canonical document, Markdown, and chunk artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from sourcecode.representation.markdown_builder import build_chunk_markdown, build_markdown
from sourcecode.representation.schemas import CanonicalDocument, DocumentChunk


def save_document(document: CanonicalDocument, output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / f"{document.document_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document.model_dump(mode="json"), indent=2), encoding="utf-8")
    return output_path


def save_markdown(document: CanonicalDocument, output_dir: str | Path, chunks: list[DocumentChunk] | None = None) -> Path:
    output_path = Path(output_dir) / f"{document.document_id}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = build_chunk_markdown(document, chunks) if chunks is not None else build_markdown(document)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def save_chunks(chunks: list[DocumentChunk], document_id: str, output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / f"{document_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def load_chunks(path: str | Path) -> list[DocumentChunk]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TypeAdapter(list[DocumentChunk]).validate_python(payload)
