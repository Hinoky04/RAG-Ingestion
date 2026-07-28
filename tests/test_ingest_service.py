from __future__ import annotations

import json

from src.parsers.base_parser import BaseParser
from src.pipeline.ingest_service import ingest_record
from src.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


class FakeParser(BaseParser):
    parser_name = "fake"
    parser_version = "v-test"

    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        return CanonicalDocument(
            document_id=record.document_id,
            client_id=record.client_id,
            document_type=record.document_type,
            source_path=record.source_path,
            file_name=record.file_name,
            version=record.version,
            access_scope=record.access_scope,
            blocks=[
                ParsedBlock(
                    document_id=record.document_id,
                    page_number=1,
                    block_type=BlockType.HEADING,
                    text="Refund SOP",
                    heading_level=1,
                    source_path=record.source_path,
                    parser_name=self.parser_name,
                ),
                ParsedBlock(
                    document_id=record.document_id,
                    page_number=1,
                    block_type=BlockType.TEXT,
                    text="If the refund exceeds RM500, escalate to a supervisor immediately.",
                    source_path=record.source_path,
                    parser_name=self.parser_name,
                ),
            ],
        )


def test_ingest_record_writes_all_artifacts(tmp_path):
    record = DocumentRecord(
        source_path="data/raw/client_a/refund_sop.pdf",
        file_name="refund_sop.pdf",
        file_type="pdf",
        checksum="abc123",
        client_id="client_a",
        document_type="sop",
    )

    outcome = ingest_record(
        record=record,
        output_dir=tmp_path / "documents",
        markdown_dir=tmp_path / "markdown",
        chunk_dir=tmp_path / "chunks",
        parser=FakeParser(),
    )

    assert outcome.parser_name == "fake"
    assert outcome.artifacts.document_path.exists()
    assert outcome.artifacts.markdown_path is not None
    assert outcome.artifacts.markdown_path.exists()
    assert outcome.artifacts.chunk_path is not None
    assert outcome.artifacts.chunk_path.exists()
    assert len(outcome.chunks) == 1

    payload = json.loads(outcome.artifacts.chunk_path.read_text(encoding="utf-8"))
    assert payload[0]["client_id"] == "client_a"
    assert "RM500" in payload[0]["text"]
