from streamlit_app import DEFAULT_COLLECTION, infer_document_type


def test_pdf_upload_defaults_to_document():
    assert infer_document_type("Article 42.pdf") == "document"


def test_docx_upload_defaults_to_document():
    assert infer_document_type("Article 42.docx") == "document"


def test_unsupported_upload_is_unknown():
    assert infer_document_type("Article 42.txt") == "unknown"


def test_retrieval_collection_is_fixed_to_rag_ingestion():
    assert DEFAULT_COLLECTION == "rag_ingestion"


def test_index_pipeline_defaults_to_rag_ingestion(monkeypatch):
    from src.pipeline.index_pipeline import parse_args

    monkeypatch.setattr("sys.argv", ["index_pipeline"])
    assert parse_args().collection == "rag_ingestion"


def test_searcher_defaults_to_rag_ingestion(monkeypatch):
    from src.retrieval.searcher import parse_args

    monkeypatch.setattr("sys.argv", ["searcher", "query"])
    assert parse_args().collection == "rag_ingestion"
