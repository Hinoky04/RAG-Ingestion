from __future__ import annotations

from datetime import datetime, timezone

from src.pipeline.ingest_service import IngestionArtifacts, IngestionOutcome
from src.representation.schemas import CanonicalDocument, DocumentChunk, DocumentRecord, ParsedBlock
from src.workspace.models import WorkspaceDocument
from src.workspace.service import WorkspaceService


def test_workspace_service_register_ingest_validate_index(tmp_path, monkeypatch):
    raw_file = tmp_path / "credit_card_policy.pdf"
    raw_file.write_bytes(b"%PDF-1.4")

    class FakeWorkspace:
        backend_name = "postgresql"
        location_label = "postgresql://local/test"

        def __init__(self) -> None:
            self.documents: dict[str, WorkspaceDocument] = {}
            self.chunk_rows: dict[str, list[dict]] = {}

        def upsert_document(self, record: DocumentRecord, status: str = "registered") -> str:
            document = WorkspaceDocument(
                document_id=record.document_id,
                source_path=record.source_path,
                file_name=record.file_name,
                file_type=record.file_type,
                checksum=record.checksum,
                client_id=record.client_id,
                document_type=record.document_type,
                version=record.version,
                access_scope=record.access_scope,
                status=status,
                parser_name=None,
                parser_version=None,
                collection_name=None,
                error_message=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                approved_at=None,
                indexed_at=None,
            )
            self.documents[document.document_id] = document
            return document.document_id

        def get_document(self, document_id: str) -> WorkspaceDocument | None:
            return self.documents.get(document_id)

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
        ) -> None:
            document = self.documents[document_id]
            document.status = status
            document.parser_name = parser_name
            document.parser_version = parser_version
            document.artifacts = dict(artifacts)
            document.updated_at = datetime.now(timezone.utc)
            self.chunk_rows[document_id] = list(chunks or [])

        def record_ingestion_failure(self, document_id: str, error_message: str) -> None:
            document = self.documents[document_id]
            document.status = "failed"
            document.error_message = error_message
            document.updated_at = datetime.now(timezone.utc)

        def list_chunks(self, document_id: str) -> list[dict]:
            return list(self.chunk_rows.get(document_id, []))

        def mark_indexed(self, document_id: str, collection_name: str) -> None:
            document = self.documents[document_id]
            document.status = "indexed"
            document.collection_name = collection_name
            document.indexed_at = datetime.now(timezone.utc)
            for row in self.chunk_rows.get(document_id, []):
                row["indexed_at"] = document.indexed_at.isoformat()

    fake_workspace = FakeWorkspace()
    monkeypatch.setattr("src.workspace.service.create_workspace_store", lambda database_url=None: fake_workspace)

    service = WorkspaceService(
        upload_dir=tmp_path / "uploads",
        document_dir=tmp_path / "documents",
        markdown_dir=tmp_path / "markdown",
        chunk_dir=tmp_path / "chunks",
    )
    record = service.register_path(raw_file, client_id="bank_a", document_type="credit_card")

    document_json = tmp_path / "documents" / f"{record.document_id}.json"
    markdown_file = tmp_path / "markdown" / f"{record.document_id}.md"
    chunk_file = tmp_path / "chunks" / f"{record.document_id}.json"
    document_json.parent.mkdir(parents=True, exist_ok=True)
    markdown_file.parent.mkdir(parents=True, exist_ok=True)
    chunk_file.parent.mkdir(parents=True, exist_ok=True)
    document_json.write_text("{}", encoding="utf-8")
    markdown_file.write_text("# Preview", encoding="utf-8")
    chunk_file.write_text("[]", encoding="utf-8")

    def fake_ingest_record(**kwargs):
        record_arg: DocumentRecord = kwargs["record"]
        block = ParsedBlock(
            document_id=record_arg.document_id,
            block_type="text",
            text="Card disputes must be escalated within 24 hours.",
            source_path=record_arg.source_path,
            parser_name="fake-pdf",
            parser_version="v1",
        )
        chunk = DocumentChunk(
            document_id=record_arg.document_id,
            client_id=record_arg.client_id,
            document_type=record_arg.document_type,
            source_path=record_arg.source_path,
            file_name=record_arg.file_name,
            text="Card disputes must be escalated within 24 hours.",
            source_block_ids=[block.block_id],
        )
        return IngestionOutcome(
            document=CanonicalDocument(
                document_id=record_arg.document_id,
                client_id=record_arg.client_id,
                document_type=record_arg.document_type,
                source_path=record_arg.source_path,
                file_name=record_arg.file_name,
                version=record_arg.version,
                access_scope=record_arg.access_scope,
                blocks=[block],
            ),
            chunks=[chunk],
            parser_name="fake-pdf",
            parser_version="v1",
            artifacts=IngestionArtifacts(
                document_path=document_json,
                markdown_path=markdown_file,
                chunk_path=chunk_file,
            ),
        )

    monkeypatch.setattr("src.workspace.service.ingest_record", fake_ingest_record)
    outcome = service.ingest_document(record.document_id)
    assert outcome.parser_name == "fake-pdf"

    stored = service.workspace.get_document(record.document_id)
    assert stored is not None
    assert stored.status == "validated"
    assert stored.artifacts["markdown"] == str(markdown_file)
    stored_chunks = service.workspace.list_chunks(record.document_id)
    assert len(stored_chunks) == 1
    assert stored_chunks[0]["chunk_id"].startswith("chunk_")
    assert stored_chunks[0]["section_path"] == "Unknown Section"

    monkeypatch.setattr(
        "src.workspace.service.load_chunks",
        lambda path: [
            DocumentChunk(
                document_id=record.document_id,
                client_id="bank_a",
                document_type="credit_card",
                source_path=str(raw_file),
                file_name=raw_file.name,
                text="Card disputes must be escalated within 24 hours.",
            )
        ],
    )
    monkeypatch.setattr("src.workspace.service.index_document_chunks", lambda **kwargs: 1)
    indexed_count = service.index_document(record.document_id, collection_name="credit_card_demo", persist_dir=tmp_path / "chroma")
    assert indexed_count == 1

    indexed = service.workspace.get_document(record.document_id)
    assert indexed is not None
    assert indexed.status == "indexed"
    assert indexed.collection_name == "credit_card_demo"
    indexed_chunks = service.workspace.list_chunks(record.document_id)
    assert indexed_chunks[0]["indexed_at"] is not None


def test_workspace_document_display_id_is_readable():
    document = WorkspaceDocument(
        document_id="doc_abc123456789",
        source_path="data/raw/maybank/sample.pdf",
        file_name="Maybank Report Disputed Transaction.pdf",
        file_type="pdf",
        checksum="abc",
        client_id="maybank",
        document_type="guidance_page",
        version="v1",
        access_scope="internal",
        status="registered",
        parser_name=None,
        parser_version=None,
        collection_name=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        approved_at=None,
        indexed_at=None,
    )

    assert document.display_id.startswith("doc_maybank_guidance_page_")
    assert document.display_id.endswith("_6789")
