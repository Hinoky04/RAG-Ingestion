from sourcecode.processing.chunker import chunk_document
from sourcecode.processing.quality import assess_chunks
from sourcecode.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def test_chunk_identity_and_quality_are_stable_without_changing_evidence():
    document = CanonicalDocument(
        document_id="doc_stable",
        source_path="source.docx",
        file_name="source.docx",
        blocks=[
            ParsedBlock(
                block_id="block_stable",
                document_id="doc_stable",
                source_path="source.docx",
                parser_name="test",
                block_type=BlockType.TEXT,
                text="This evidence remains unchanged while gaining a stable retrieval identity.",
                metadata={"paragraph_index": 4},
            )
        ],
    )

    first = chunk_document(document)
    second = chunk_document(document)
    report = assess_chunks(first)

    assert first[0].text == second[0].text
    assert first[0].chunk_id == second[0].chunk_id
    assert first[0].metadata["source_anchor"] == "paragraph:4"
    assert report.chunks_without_provenance == 0
    assert report.chunks_without_locator == 0
