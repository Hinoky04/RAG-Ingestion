from __future__ import annotations

from typing import Protocol

from src.representation.schemas import DocumentRecord
from src.workspace.models import WorkspaceDocument


class WorkspaceStore(Protocol):
    backend_name: str
    location_label: str

    def upsert_document(self, record: DocumentRecord, status: str = "registered") -> str: ...

    def record_ingestion_success(
        self,
        document_id: str,
        parser_name: str,
        parser_version: str,
        artifacts: dict[str, str],
        status: str = "validated",
        validation_summary: dict | None = None,
        validation_events: list[dict] | None = None,
        chunks: list[dict] | None = None,
    ) -> None: ...

    def record_ingestion_failure(self, document_id: str, error_message: str) -> None: ...

    def mark_indexed(self, document_id: str, collection_name: str) -> None: ...

    def list_documents(self, status: str | None = None) -> list[WorkspaceDocument]: ...

    def get_document(self, document_id: str) -> WorkspaceDocument | None: ...

    def stats(self) -> dict[str, int]: ...

    def get_latest_validation_summary(self, document_id: str) -> dict | None: ...

    def list_chunks(self, document_id: str) -> list[dict]: ...
