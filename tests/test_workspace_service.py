from datetime import datetime, timezone

from src.pipeline.ingest_service import IngestionArtifacts, IngestionOutcome
from src.representation.schemas import CanonicalDocument, DocumentChunk, DocumentRecord, ParsedBlock
from src.workspace.models import WorkspaceDocument
from src.workspace.service import WorkspaceService, next_version_label


def test_next_version_label_increments_decimal_versions():
    assert next_version_label([]) == "v1"
    assert next_version_label(["v1"]) == "1.1"
    assert next_version_label(["v1", "1.1", "1.2"]) == "1.3"
    assert next_version_label(["1.8"]) == "1.9"
    assert next_version_label(["1.9"]) == "2.0"


def test_workspace_service_registers_validates_and_indexes(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, _dsn: str) -> None:
            self.documents: dict[str, WorkspaceDocument] = {}

        def upsert_document(self, record: DocumentRecord, status: str = "registered") -> str:
            document = WorkspaceDocument(
                document_id=record.document_id, source_path=record.source_path, file_name=record.file_name,
                file_type=record.file_type, checksum=record.checksum, document_type=record.document_type,
                version=record.version, status=status, parser_name=None, parser_version=None,
                collection_name=None, error_message=None, created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc), indexed_at=None,
            )
            self.documents[document.document_id] = document
            return document.document_id

        def get_document(self, document_id: str):
            return self.documents.get(document_id)

        def get_document_by_checksum(self, checksum: str):
            return next((document for document in self.documents.values() if document.checksum == checksum), None)

        def list_documents_by_filename(self, file_name: str):
            return [document for document in self.documents.values() if document.file_name == file_name]

        def record_ingestion_success(self, document_id, parser_name, parser_version, artifacts, status="validated", **_kwargs):
            document = self.documents[document_id]
            document.status = status
            document.parser_name = parser_name
            document.parser_version = parser_version
            document.artifacts = artifacts

        def record_ingestion_failure(self, document_id, error_message):
            self.documents[document_id].status = "failed"

        def mark_indexed(self, document_id, collection_name):
            document = self.documents[document_id]
            document.status = "indexed"
            document.collection_name = collection_name

        def mark_unindexed(self, document_id, status="validated"):
            document = self.documents[document_id]
            document.status = status
            document.collection_name = None

        def delete_document(self, document_id):
            self.documents.pop(document_id, None)

    monkeypatch.setattr("src.workspace.service.PostgreSQLWorkspace", FakeWorkspace)
    source = tmp_path / "article.pdf"
    source.write_bytes(b"%PDF-1.4")
    service = WorkspaceService(database_url="postgresql://test", document_dir=tmp_path / "documents", markdown_dir=tmp_path / "markdown", chunk_dir=tmp_path / "chunks")
    record = service.register_path(source, document_type="kb_article")
    assert service.find_document_by_checksum(b"%PDF-1.4").document_id == record.document_id

    block = ParsedBlock(document_id=record.document_id, text="Escalate within 24 hours.", source_path=record.source_path, parser_name="fake")
    chunk = DocumentChunk(document_id=record.document_id, document_type="kb_article", source_path=record.source_path, file_name=record.file_name, text=block.text)
    artifact = tmp_path / "chunks.json"
    artifact.write_text("[]", encoding="utf-8")
    outcome = IngestionOutcome(
        document=CanonicalDocument(document_id=record.document_id, document_type="kb_article", source_path=record.source_path, file_name=record.file_name, blocks=[block]),
        chunks=[chunk], parser_name="fake", parser_version="v1",
        artifacts=IngestionArtifacts(tmp_path / "document.json", tmp_path / "preview.md", artifact),
    )
    monkeypatch.setattr("src.workspace.service.ingest_record", lambda **_kwargs: outcome)
    service.ingest_document(record.document_id)
    assert service.workspace.get_document(record.document_id).status == "validated"

    monkeypatch.setattr("src.workspace.service.load_chunks", lambda _path: [chunk])
    monkeypatch.setattr("src.workspace.service.index_document_chunks", lambda **_kwargs: 1)
    assert service.index_document(record.document_id, "kb_articles", tmp_path / "chroma") == 1
    assert service.workspace.get_document(record.document_id).status == "indexed"

    updated_source = tmp_path / "article-updated.pdf"
    updated_source.write_bytes(b"%PDF-1.5")
    updated_record = service.register_path(updated_source, document_type="kb_article", version=service.suggested_version_for_filename(source.name))
    assert updated_record.version == "1.1"


def test_workspace_service_can_remove_from_index_and_delete_document(tmp_path, monkeypatch):
    deleted_ids: list[str] = []

    class FakeWorkspace:
        def __init__(self, _dsn: str) -> None:
            source = tmp_path / "uploads" / "document" / "article.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("source", encoding="utf-8")
            self.documents = {
                "doc-1": WorkspaceDocument(
                    document_id="doc-1",
                    source_path=str(source),
                    file_name="article.pdf",
                    file_type="pdf",
                    checksum="abc",
                    document_type="document",
                    version="v1",
                    status="indexed",
                    parser_name="fake",
                    parser_version="v1",
                    collection_name="rag_ingestion",
                    error_message=None,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    indexed_at=datetime.now(timezone.utc),
                        artifacts={
                            "document_json": str(tmp_path / "documents" / "doc-1.json"),
                            "markdown": str(tmp_path / "markdown" / "doc-1.md"),
                            "chunks": str(tmp_path / "chunks" / "doc-1.json"),
                        },
                    )
                }

        def get_document(self, document_id: str):
            return self.documents.get(document_id)

        def list_documents_by_filename(self, file_name: str):
            return [document for document in self.documents.values() if document.file_name == file_name]

        def mark_unindexed(self, document_id, status="validated"):
            document = self.documents[document_id]
            document.status = status
            document.collection_name = None
            document.indexed_at = None

        def delete_document(self, document_id):
            self.documents.pop(document_id, None)

    class FakeStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def delete_document_chunks(self, document_id: str) -> None:
            deleted_ids.append(document_id)

    document_path = tmp_path / "documents" / "doc-1.json"
    markdown_path = tmp_path / "markdown" / "doc-1.md"
    chunk_path = tmp_path / "chunks" / "doc-1.json"
    for path in (document_path, markdown_path, chunk_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")

    monkeypatch.setattr("src.workspace.service.PostgreSQLWorkspace", FakeWorkspace)
    monkeypatch.setattr("src.workspace.service.ChromaChunkStore", FakeStore)

    service = WorkspaceService(
        database_url="postgresql://test",
        upload_dir=tmp_path / "uploads",
        document_dir=tmp_path / "documents",
        markdown_dir=tmp_path / "markdown",
        chunk_dir=tmp_path / "chunks",
    )

    service.remove_document_from_index("doc-1", tmp_path / "chroma")
    assert deleted_ids == ["doc-1"]
    assert service.workspace.get_document("doc-1").status == "validated"

    service.delete_document("doc-1", tmp_path / "chroma")
    assert deleted_ids == ["doc-1"]
    assert service.workspace.get_document("doc-1") is None
    assert not document_path.exists()
    assert not markdown_path.exists()
    assert not chunk_path.exists()


def test_save_uploaded_file_uses_unique_checksum_directory(tmp_path, monkeypatch):
    class FakeWorkspace:
        def __init__(self, _dsn: str) -> None:
            pass

    monkeypatch.setattr("src.workspace.service.PostgreSQLWorkspace", FakeWorkspace)
    service = WorkspaceService(database_url="postgresql://test", upload_dir=tmp_path / "uploads")

    first = service.save_uploaded_file("article.docx", b"alpha", "document")
    second = service.save_uploaded_file("article.docx", b"beta", "document")

    assert first.name == "article.docx"
    assert second.name == "article.docx"
    assert first != second
    assert first.read_bytes() == b"alpha"
    assert second.read_bytes() == b"beta"
