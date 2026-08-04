from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.parsers.base_parser import BaseParser
from src.pipeline.common import parser_for, save_chunks, save_document, save_markdown
from src.processing.chunker import chunk_document
from src.processing.cleaner import clean_document
from src.processing.quality import ChunkQualityReport, assess_chunks
from src.representation.schemas import CanonicalDocument, DocumentChunk, DocumentRecord


@dataclass
class IngestionArtifacts:
    document_path: Path
    markdown_path: Path | None
    chunk_path: Path | None


@dataclass
class IngestionOutcome:
    document: CanonicalDocument
    chunks: list[DocumentChunk]
    parser_name: str
    parser_version: str
    artifacts: IngestionArtifacts
    quality: ChunkQualityReport | None = None


def ingest_record(
    record: DocumentRecord,
    output_dir: str | Path,
    markdown_dir: str | Path | None,
    chunk_dir: str | Path | None,
    parser: BaseParser | None = None,
) -> IngestionOutcome:
    selected_parser = parser or parser_for(record)
    if selected_parser is None:
        raise ValueError(f"Unsupported file type: {record.file_type}")

    document = clean_document(selected_parser.parse(record))
    document = document.model_copy(update={"metadata": {**document.metadata, "source_checksum": record.checksum}})
    document_path = save_document(document, output_dir)

    chunks = chunk_document(document) if markdown_dir is not None or chunk_dir is not None else []
    quality = assess_chunks(chunks)

    markdown_path: Path | None = None
    if markdown_dir is not None:
        markdown_path = save_markdown(document, markdown_dir, chunks)

    chunk_path: Path | None = None
    if chunk_dir is not None:
        chunk_path = save_chunks(chunks, document.document_id, chunk_dir)

    return IngestionOutcome(
        document=document,
        chunks=chunks,
        parser_name=selected_parser.parser_name,
        parser_version=selected_parser.parser_version,
        artifacts=IngestionArtifacts(
            document_path=document_path,
            markdown_path=markdown_path,
            chunk_path=chunk_path,
        ),
        quality=quality,
    )
