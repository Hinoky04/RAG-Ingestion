from streamlit_app import DEFAULT_COLLECTION, UPLOAD_VERSION_PATTERN, user_facing_processing_error, validate_retrieval_query


def test_submission_uses_expected_collection_and_numeric_versions():
    assert DEFAULT_COLLECTION == "rag_ingestion"
    assert UPLOAD_VERSION_PATTERN.fullmatch("1.2")
    assert not UPLOAD_VERSION_PATTERN.fullmatch("v1")


def test_retrieval_rejects_empty_short_and_invalid_queries():
    assert validate_retrieval_query("")
    assert validate_retrieval_query("hello")
    assert validate_retrieval_query("<script>alert(1)</script>")
    assert validate_retrieval_query("What is the refund policy?") is None


def test_missing_upload_error_has_actionable_message():
    message = user_facing_processing_error(FileNotFoundError("private/path/file.docx"))
    assert "upload" in message.lower()
    assert "private/path" not in message
