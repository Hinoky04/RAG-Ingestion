"""Opt-in real pipeline smoke test; use a disposable database only."""

import os
from pathlib import Path
import pytest
from sourcecode.indexing.embedder import LocalEmbedder
from sourcecode.indexing.chroma_store import ChromaChunkStore
from sourcecode.retrieval.searcher import search
from sourcecode.workspace.service import WorkspaceService


@pytest.fixture(scope="module")
def local_model():
    if not os.environ.get("RAG_TEST_DATABASE_URL"):
        pytest.skip("Set RAG_TEST_DATABASE_URL to an empty disposable database")
    return LocalEmbedder(cache_dir=Path(os.environ.get("RAG_TEST_MODEL_CACHE", ".cache/huggingface")))


@pytest.mark.integration
@pytest.mark.parametrize("file_type", ["pdf", "docx"])
def test_real_upload_review_index_retrieve_and_remove(tmp_path, monkeypatch, local_model, file_type):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    dsn = os.environ["RAG_TEST_DATABASE_URL"]
    assert conninfo_to_dict(dsn).get("dbname", "").endswith("_test"), "Use a disposable *_test database"
    monkeypatch.setattr("sourcecode.pipeline.index_service.LocalEmbedder", lambda **_: local_model)
    monkeypatch.setattr("sourcecode.retrieval.searcher.LocalEmbedder", lambda **_: local_model)
    service = WorkspaceService(database_url=dsn, upload_dir=tmp_path / "uploads", document_dir=tmp_path / "documents", markdown_dir=tmp_path / "markdown", chunk_dir=tmp_path / "chunks")
    source = tmp_path / ("refund_policy." + file_type)
    evidence = "Refund requests must be submitted within 30 days. Escalate refunds above RM500 to a supervisor."
    if file_type == "docx":
        from docx import Document
        document = Document()
        document.add_heading("Refund Policy", level=1)
        document.add_paragraph(evidence)
        document.save(source)
    else:
        import fitz
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Refund Policy", fontsize=18)
        page.insert_textbox((72, 110, 520, 260), evidence, fontsize=12)
        document.save(source)
        document.close()
    payload = source.read_bytes()
    service.validate_upload(source.name, payload)
    managed = service.save_uploaded_file(source.name, payload, "document")
    record = service.register_path(managed, "document")
    outcome = service.ingest_document(record.document_id)
    assert outcome.chunks
    assert all(p.exists() for p in [outcome.artifacts.document_path, outcome.artifacts.markdown_path, outcome.artifacts.chunk_path])
    assert service.workspace.get_document(record.document_id).status == "review_ready"
    collection = "smoke_" + file_type
    vectors = tmp_path / "chroma"
    with pytest.raises(ValueError, match="manually approved"):
        service.index_document(record.document_id, collection, vectors)
    service.approve_document(record.document_id)
    indexed = service.index_document(record.document_id, collection, vectors)
    assert indexed == len(outcome.chunks)
    assert service.workspace.get_document(record.document_id).status == "indexed"
    hits = search("How many days do I have to submit a refund?", collection, persist_dir=vectors)
    assert hits and hits[0].document_id == record.document_id
    assert "30 days" in hits[0].text
    assert hits[0].citation
    assert service.index_document(record.document_id, collection, vectors) == indexed
    store = ChromaChunkStore(persist_dir=vectors, collection_name=collection)
    assert store.collection.count() == indexed
    with pytest.raises(ValueError, match="Remove this document"):
        service.ingest_document(record.document_id)
    assert service.source_download(record.document_id)[1] == payload
    service.remove_document_from_index(record.document_id, vectors)
    assert store.collection.count() == 0
    service.delete_document(record.document_id, vectors)
    assert service.workspace.get_document(record.document_id) is None
    assert not managed.exists()
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM documents WHERE document_id = %s", (record.document_id,)).fetchone()[0] == 0
