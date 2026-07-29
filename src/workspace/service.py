from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from src.indexing.chroma_store import ChromaChunkStore, DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAME
from src.indexing.embedder import DEFAULT_MODEL_NAME
from src.pipeline.index_pipeline import load_chunks
from src.pipeline.index_service import index_document_chunks
from src.pipeline.ingest_service import IngestionOutcome, ingest_record
from src.registry.checksum import calculate_checksum
from src.registry.source_registry import display_path
from src.representation.schemas import DocumentRecord
from src.workspace.postgres_workspace import PostgreSQLWorkspace


DEFAULT_UPLOAD_DIR = Path("data/raw/workspace_uploads")
DEFAULT_DOCUMENT_DIR = Path("data/processed/workspace/documents")
DEFAULT_MARKDOWN_DIR = Path("data/processed/workspace/markdown")
DEFAULT_CHUNK_DIR = Path("data/processed/workspace/chunks")


def build_validation_report(outcome: IngestionOutcome) -> tuple[str, dict, list[dict]]:
    # Keep validation deterministic for now: this checks whether the parser
    # produced usable structure, not whether the business content is correct.
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

    status = "validated" if block_count > 0 and chunk_count > 0 and artifact_presence["chunks"] else "low_confidence"
    summary["automation_status"] = status
    return status, summary, events


def chunk_records_for_workspace(outcome: IngestionOutcome) -> list[dict]:
    # PostgreSQL tracks chunk identity and trace metadata; full text stays in
    # the chunk artifact and vector store to keep the control database light.
    records: list[dict] = []
    for index, chunk in enumerate(outcome.chunks, start=1):
        records.append(
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
        )
    return records


VERSION_PATTERN = re.compile(r"^(?:v)?(\d+)(?:\.(\d+))?$", re.IGNORECASE)


def parse_version_number(value: str) -> tuple[int, int] | None:
    match = VERSION_PATTERN.match(value.strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major, minor


def next_version_label(existing_versions: list[str]) -> str:
    parsed_versions = [parsed for version in existing_versions if (parsed := parse_version_number(version)) is not None]
    if not parsed_versions:
        return "v1"

    major, minor = max(parsed_versions)
    if minor == 0:
        return f"{major}.1"
    if minor < 9:
        return f"{major}.{minor + 1}"
    return f"{major + 1}.0"


class WorkspaceService:
    def __init__(
        self,
        upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
        document_dir: str | Path = DEFAULT_DOCUMENT_DIR,
        markdown_dir: str | Path = DEFAULT_MARKDOWN_DIR,
        chunk_dir: str | Path = DEFAULT_CHUNK_DIR,
        database_url: str | None = None,
    ) -> None:
        dsn = database_url or os.getenv("WORKSPACE_DATABASE_URL")
        if not dsn:
            raise RuntimeError("Set WORKSPACE_DATABASE_URL to use the ingestion workspace.")
        self.workspace = PostgreSQLWorkspace(dsn)
        self.upload_dir = Path(upload_dir)
        self.document_dir = Path(document_dir)
        self.markdown_dir = Path(markdown_dir)
        self.chunk_dir = Path(chunk_dir)

    def _safe_delete_file(self, path_value: str | Path, allowed_roots: list[Path]) -> None:
        candidate = Path(path_value)
        try:
            resolved = candidate.resolve()
        except OSError:
            return

        allowed = [root.resolve() for root in allowed_roots]
        if not any(root == resolved or root in resolved.parents for root in allowed):
            return

        try:
            resolved.unlink(missing_ok=True)
        except OSError:
            return

    def save_uploaded_file(
        self,
        file_name: str,
        file_bytes: bytes,
        document_type: str,
    ) -> Path:
        target_dir = self.upload_dir / document_type
        target_dir.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256(file_bytes).hexdigest()[:12]
        target_path = target_dir / checksum / file_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(file_bytes)
        return target_path

    def find_document_by_checksum(self, file_bytes: bytes):
        checksum = hashlib.sha256(file_bytes).hexdigest()
        return self.workspace.get_document_by_checksum(checksum)

    def suggested_version_for_filename(self, file_name: str) -> str:
        documents = self.workspace.list_documents_by_filename(file_name)
        return next_version_label([document.version for document in documents])

    def register_path(
        self,
        file_path: str | Path,
        document_type: str,
        version: str = "v1",
    ) -> DocumentRecord:
        path = Path(file_path)
        record = DocumentRecord(
            source_path=display_path(path),
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            checksum=calculate_checksum(path),
            document_type=document_type,
            version=version,
        )
        document_id = self.workspace.upsert_document(record, status="registered")
        return record.model_copy(update={"document_id": document_id})

    def ingest_document(self, document_id: str) -> IngestionOutcome:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")

        record = DocumentRecord(
            document_id=document.document_id,
            source_path=document.source_path,
            file_name=document.file_name,
            file_type=document.file_type,
            checksum=document.checksum,
            document_type=document.document_type,
            version=document.version,
        )

        try:
            outcome = ingest_record(
                record=record,
                output_dir=self.document_dir,
                markdown_dir=self.markdown_dir,
                chunk_dir=self.chunk_dir,
            )
        except Exception as exc:
            self.workspace.record_ingestion_failure(document_id, str(exc))
            raise

        artifacts = {
            "document_json": str(outcome.artifacts.document_path),
        }
        if outcome.artifacts.markdown_path is not None:
            artifacts["markdown"] = str(outcome.artifacts.markdown_path)
        if outcome.artifacts.chunk_path is not None:
            artifacts["chunks"] = str(outcome.artifacts.chunk_path)

        validation_status, validation_summary, validation_events = build_validation_report(outcome)
        self.workspace.record_ingestion_success(
            document_id=document_id,
            parser_name=outcome.parser_name,
            parser_version=outcome.parser_version,
            artifacts=artifacts,
            status=validation_status,
            validation_summary=validation_summary,
            validation_events=validation_events,
            chunks=chunk_records_for_workspace(outcome),
        )
        return outcome

    def index_document(
        self,
        document_id: str,
        collection_name: str,
        persist_dir: str | Path,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> int:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")
        if document.status not in {"validated", "indexed"}:
            raise ValueError("Document must pass automated validation before indexing")
        chunk_path = document.artifacts.get("chunks")
        if not chunk_path:
            raise ValueError("No chunk artifact found for this document")

        chunks = load_chunks(chunk_path)
        indexed_count = index_document_chunks(
            chunks=chunks,
            collection_name=collection_name,
            persist_dir=persist_dir,
            model_name=model_name,
        )
        self.workspace.mark_indexed(document_id, collection_name=collection_name)
        return indexed_count

    def remove_document_from_index(
        self,
        document_id: str,
        persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    ) -> None:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")
        if document.status != "indexed":
            raise ValueError("Only indexed documents can be removed from ChromaDB")

        collection_name = document.collection_name or DEFAULT_COLLECTION_NAME
        store = ChromaChunkStore(persist_dir=persist_dir, collection_name=collection_name)
        store.delete_document_chunks(document_id)
        self.workspace.mark_unindexed(document_id, status="validated")

    def delete_document(
        self,
        document_id: str,
        persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    ) -> None:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")

        if document.collection_name or document.status == "indexed":
            collection_name = document.collection_name or DEFAULT_COLLECTION_NAME
            store = ChromaChunkStore(persist_dir=persist_dir, collection_name=collection_name)
            store.delete_document_chunks(document_id)

        for artifact_path in document.artifacts.values():
            self._safe_delete_file(artifact_path, [self.document_dir, self.markdown_dir, self.chunk_dir])

        self._safe_delete_file(document.source_path, [self.upload_dir])
        self.workspace.delete_document(document_id)
