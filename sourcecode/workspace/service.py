"""Workspace operations used by the Streamlit application."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sourcecode.indexing.chroma_store import ChromaChunkStore, DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAME
from sourcecode.indexing.embedder import DEFAULT_MODEL_NAME
from sourcecode.pipeline.artifacts import load_chunks
from sourcecode.pipeline.index_service import index_document_chunks
from sourcecode.pipeline.ingest_service import IngestionOutcome, ingest_record
from sourcecode.registry.checksum import calculate_checksum
from sourcecode.registry.source_registry import display_path
from sourcecode.representation.schemas import DocumentRecord
from sourcecode.workspace.files import read_managed_source, safe_delete_file, safe_upload_name, save_uploaded_file
from sourcecode.workspace.postgres_workspace import PostgreSQLWorkspace
from sourcecode.workspace.validation import build_validation_report, chunk_records_for_workspace
from sourcecode.workspace.versioning import next_version_label


DEFAULT_UPLOAD_DIR = Path("data/raw/workspace_uploads")
DEFAULT_DOCUMENT_DIR = Path("data/processed/workspace/documents")
DEFAULT_MARKDOWN_DIR = Path("data/processed/workspace/markdown")
DEFAULT_CHUNK_DIR = Path("data/processed/workspace/chunks")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class WorkspaceService:
    """Operations called by the Streamlit upload and review screens."""
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

    def save_uploaded_file(
        self,
        file_name: str,
        file_bytes: bytes,
        document_type: str,
    ) -> Path:
        return save_uploaded_file(self.upload_dir, file_name, file_bytes, document_type)

    def validate_upload(self, file_name: str, file_bytes: bytes) -> None:
        safe_upload_name(file_name)
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError("File exceeds the 200MB local upload limit")

    def find_document_by_checksum(self, file_bytes: bytes):
        checksum = hashlib.sha256(file_bytes).hexdigest()
        return self.workspace.get_document_by_checksum(checksum)

    def suggested_version_for_filename(self, file_name: str) -> str:
        documents = self.workspace.list_documents_by_filename(safe_upload_name(file_name))
        return next_version_label([document.version for document in documents])

    def register_path(
        self,
        file_path: str | Path,
        document_type: str,
        version: str = "1",
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

    def approve_document(self, document_id: str) -> None:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")
        if document.status != "review_ready":
            raise ValueError("Only review-ready documents can be approved for indexing")
        self.workspace.mark_approved(document_id)

    def ingest_document(self, document_id: str) -> IngestionOutcome:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")
        if document.status == "indexed":
            raise ValueError("Remove this document from the index before re-processing it")

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
            # Re-process failed. Old vectors cannot stay as current text.
            if document.collection_name:
                try:
                    store = ChromaChunkStore(
                        persist_dir=DEFAULT_CHROMA_DIR,
                        collection_name=document.collection_name,
                    )
                    store.delete_document_chunks(document_id)
                except Exception:
                    # Keep first parse error. Cleanup error is second problem.
                    pass
            self.workspace.record_ingestion_failure(document_id, str(exc))
            raise

        # Save artifact paths together because they are from one run.
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
        if document.status not in {"approved", "validated", "indexed"}:
            raise ValueError("Document must be manually approved before indexing")
        chunk_path = document.artifacts.get("chunks")
        if not chunk_path:
            raise ValueError("No chunk artifact found for this document")

        # Change database status only after ChromaDB replacement is done.
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
        self.workspace.mark_unindexed(document_id)

    def delete_document(
        self,
        document_id: str,
        persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    ) -> None:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")

        # Delete vectors first. If it fails, document record stays for retry.
        if document.collection_name or document.status == "indexed":
            collection_name = document.collection_name or DEFAULT_COLLECTION_NAME
            store = ChromaChunkStore(persist_dir=persist_dir, collection_name=collection_name)
            store.delete_document_chunks(document_id)

        for artifact_path in document.artifacts.values():
            safe_delete_file(artifact_path, [self.document_dir, self.markdown_dir, self.chunk_dir])

        safe_delete_file(document.source_path, [self.upload_dir])
        self.workspace.delete_document(document_id)

    def source_download(self, document_id: str) -> tuple[str, bytes, str]:
        document = self.workspace.get_document(document_id)
        if document is None:
            raise ValueError(f"Unknown document_id: {document_id}")

        return read_managed_source(
            source_path=document.source_path,
            file_name=document.file_name,
            file_type=document.file_type,
            upload_root=self.upload_dir,
        )
