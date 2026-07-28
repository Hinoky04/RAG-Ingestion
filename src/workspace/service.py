from __future__ import annotations

from pathlib import Path

from src.indexing.embedder import DEFAULT_MODEL_NAME
from src.pipeline.index_pipeline import load_chunks
from src.pipeline.index_service import index_document_chunks
from src.pipeline.ingest_service import IngestionOutcome, ingest_record
from src.registry.checksum import calculate_checksum
from src.registry.source_registry import display_path
from src.representation.schemas import DocumentRecord
from src.workspace.factory import create_workspace_store


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


class WorkspaceService:
    def __init__(
        self,
        upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
        document_dir: str | Path = DEFAULT_DOCUMENT_DIR,
        markdown_dir: str | Path = DEFAULT_MARKDOWN_DIR,
        chunk_dir: str | Path = DEFAULT_CHUNK_DIR,
        database_url: str | None = None,
    ) -> None:
        self.workspace = create_workspace_store(database_url=database_url)
        self.upload_dir = Path(upload_dir)
        self.document_dir = Path(document_dir)
        self.markdown_dir = Path(markdown_dir)
        self.chunk_dir = Path(chunk_dir)

    def save_uploaded_file(
        self,
        file_name: str,
        file_bytes: bytes,
        client_id: str,
        document_type: str,
    ) -> Path:
        target_dir = self.upload_dir / client_id / document_type
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        target_path.write_bytes(file_bytes)
        return target_path

    def register_path(
        self,
        file_path: str | Path,
        client_id: str,
        document_type: str,
        version: str = "v1",
        access_scope: str = "internal",
    ) -> DocumentRecord:
        path = Path(file_path)
        record = DocumentRecord(
            source_path=display_path(path),
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            checksum=calculate_checksum(path),
            client_id=client_id,
            document_type=document_type,
            version=version,
            access_scope=access_scope,
        )
        document_id = self.workspace.upsert_document(record, status="registered")
        return record.model_copy(update={"document_id": document_id})

    def ingest_document(self, document_id: str, pdf_parser: str = "pymupdf") -> IngestionOutcome:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")

        record = DocumentRecord(
            document_id=document.document_id,
            source_path=document.source_path,
            file_name=document.file_name,
            file_type=document.file_type,
            checksum=document.checksum,
            client_id=document.client_id,
            document_type=document.document_type,
            version=document.version,
            access_scope=document.access_scope,
        )

        try:
            outcome = ingest_record(
                record=record,
                output_dir=self.document_dir,
                markdown_dir=self.markdown_dir,
                chunk_dir=self.chunk_dir,
                pdf_parser=pdf_parser,
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
