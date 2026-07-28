from datetime import datetime, timezone

from streamlit_app import infer_upload_metadata, short_review_prefix
from src.workspace.models import WorkspaceDocument


def test_infer_upload_metadata_for_guidance_markdown():
    client_id, document_type = infer_upload_metadata("maybank_report_disputed_transaction.pdf")
    assert client_id == "maybank"
    assert document_type == "guidance_page"


def test_infer_upload_metadata_for_named_guidance_sample():
    client_id, document_type = infer_upload_metadata("cimb_unauthorized_transaction_guidance.pdf")
    assert client_id == "cimb"
    assert document_type == "guidance_page"


def test_infer_upload_metadata_for_dispute_form_pdf():
    client_id, document_type = infer_upload_metadata("hong_leong_dispute_form.pdf")
    assert client_id == "hong_leong"
    assert document_type == "dispute_form"


def test_short_review_prefix_is_compact():
    document = WorkspaceDocument(
        document_id="doc_abc123456789",
        source_path="data/raw/maybank/sample.pdf",
        file_name="maybank_report_disputed_transaction.pdf",
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

    assert short_review_prefix(document) == "MAYBAN-GUIDA-6789"
