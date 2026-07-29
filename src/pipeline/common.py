from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from src.parsers.base_parser import BaseParser
from src.parsers.docx_parser import DOCXParser
from src.parsers.pdf_parser import PDFParser
from src.representation.markdown_builder import build_markdown
from src.representation.schemas import CanonicalDocument, DocumentChunk, DocumentRecord


DEFAULT_REGISTRY = Path("data/processed/registry.json")
DEFAULT_OUTPUT_DIR = Path("data/processed/documents")
DEFAULT_MARKDOWN_DIR = Path("data/processed/markdown")
DEFAULT_CHUNK_DIR = Path("data/processed/chunks")


def load_registry(registry_path: str | Path) -> list[DocumentRecord]:
    path = Path(registry_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(list[DocumentRecord]).validate_python(payload)


def save_document(document: CanonicalDocument, output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / f"{document.document_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = document.model_dump(mode="json")
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def save_markdown(document: CanonicalDocument, output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / f"{document.document_id}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_markdown(document), encoding="utf-8")
    return output_path


def save_chunks(chunks: list[DocumentChunk], document_id: str, output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / f"{document_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def parser_for(record: DocumentRecord) -> BaseParser | None:
    if record.file_type.lower() == "pdf":
        return PDFParser()
    if record.file_type.lower() == "docx":
        return DOCXParser()
    return None
