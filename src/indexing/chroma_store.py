from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from chromadb.api.models.Collection import Collection

from src.representation.schemas import DocumentChunk


DEFAULT_CHROMA_DIR = Path("data/processed/chroma")
DEFAULT_COLLECTION_NAME = "rag_ingestion"


def clean_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Chroma metadata values must be simple scalar types."""

    clean: dict[str, str | int | float | bool | None] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def chunk_metadata(chunk: DocumentChunk, model_name: str) -> dict[str, str | int | float | bool | None]:
    metadata = {
        "document_id": chunk.document_id,
        "document_type": chunk.document_type,
        "source_path": chunk.source_path,
        "file_name": chunk.file_name,
        "section_path": chunk.section_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "version": chunk.version,
        "citation": chunk.citation,
        "embedding_model": model_name,
    }
    metadata.update({f"chunk_{key}": value for key, value in chunk.metadata.items()})
    return clean_metadata(metadata)


class ChromaChunkStore:
    """Thin ChromaDB wrapper for storing chunk embeddings and metadata."""

    def __init__(
        self,
        persist_dir: str | Path = DEFAULT_CHROMA_DIR,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        reset_collection: bool = False,
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection_name = collection_name
        if reset_collection:
            try:
                self.client.delete_collection(name=collection_name)
            except ValueError:
                pass
        self.collection: Collection = self.client.get_or_create_collection(name=collection_name)

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
        model_name: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return 0

        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=embeddings,
            metadatas=[chunk_metadata(chunk, model_name) for chunk in chunks],
        )
        return len(chunks)

    def count(self) -> int:
        return self.collection.count()

    def delete_document_chunks(self, document_id: str) -> None:
        """Remove prior vectors before re-indexing a document."""
        self.collection.delete(where={"document_id": document_id})
