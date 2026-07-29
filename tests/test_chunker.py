from src.processing.chunker import chunk_document, sanitize_chunk_text
from src.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def pdf_block(block_type: BlockType, text: str, heading_level: int | None = None) -> ParsedBlock:
    return ParsedBlock(
        document_id="doc-pdf",
        block_type=block_type,
        text=text,
        heading_level=heading_level,
        source_path="article.pdf",
        parser_name="pymupdf",
    )


def test_pdf_chunker_keeps_subheadings_with_major_section():
    first_body = "This section contains enough supporting context to remain a standalone retrieval unit. " * 3
    second_body = "This second section also contains enough context for a stable retrieval chunk. " * 3
    document = CanonicalDocument(
        document_id="doc-pdf",
        document_type="document",
        source_path="article.pdf",
        file_name="article.pdf",
        blocks=[
            pdf_block(BlockType.HEADING, "Document title", 2),
            pdf_block(BlockType.HEADING, "1. First section", 1),
            pdf_block(BlockType.HEADING, "Key details", 2),
            pdf_block(BlockType.TEXT, first_body),
            pdf_block(BlockType.HEADING, "2. Second section", 1),
            pdf_block(BlockType.HEADING, "More details", 2),
            pdf_block(BlockType.TEXT, second_body),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) == 3
    assert chunks[0].section_path == "Introduction"
    assert "Document title" in chunks[0].text
    assert chunks[1].section_path == "1. First section"
    assert "Key details" in chunks[1].text
    assert chunks[2].section_path == "2. Second section"
    assert "More details" in chunks[2].text


def test_docx_chunker_splits_structured_nested_table_by_column_group():
    document = CanonicalDocument(
        document_id="doc-structured-table",
        document_type="document",
        source_path="structured.docx",
        file_name="structured.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-structured-table",
                block_type=BlockType.TABLE,
                text="2. Product Details\nOffering Details...",
                source_path="structured.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {
                            "depth": 0,
                            "rows": [
                                ["2. Product Details", "2. Product Details"],
                                ["Offering Details", "Important note about plan eligibility"],
                            ],
                        },
                        {
                            "depth": 1,
                            "rows": [
                                ["Plan", "Plan 80", "Plan 100"],
                                ["Monthly Fee", "RM80", "RM100"],
                                ["Contract", "12 months", "24 months"],
                            ],
                        },
                    ]
                },
            )
        ],
    )

    chunks = chunk_document(document)

    assert [chunk.section_path for chunk in chunks] == [
        "Page unknown · Plan 80",
        "Page unknown · Plan 100",
    ]
    assert chunks[0].metadata["table_chunking"] == "structured_column_group"
    assert "Monthly Fee: RM80" in chunks[0].text
    assert "Contract: 24 months" in chunks[1].text


def test_docx_chunker_splits_generic_offer_table_by_row():
    document = CanonicalDocument(
        document_id="doc-generic-offers",
        document_type="document",
        source_path="offers.docx",
        file_name="offers.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-generic-offers",
                block_type=BlockType.TABLE,
                text="2. Product Details\nOffer table...",
                source_path="offers.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {
                            "depth": 1,
                            "rows": [
                                ["Category", "Price", "Quota (4G/5G)", "Validity"],
                                ["Daily", "RM5", "Unlimited 18Mbps", "1 Day"],
                                ["Weekly", "RM12", "20GB", "7 Days"],
                            ],
                        }
                    ]
                },
            )
        ],
    )

    chunks = chunk_document(document)

    assert [chunk.section_path for chunk in chunks] == [
        "Page unknown · Daily | RM5 | Unlimited 18Mbps",
        "Page unknown · Weekly | RM12 | 20GB",
    ]
    assert chunks[0].metadata["table_chunking"] == "structured_offer_row"
    assert "Category: Daily" in chunks[0].text
    assert "Price: RM12" in chunks[1].text


def test_sanitize_chunk_text_removes_repeated_section_lines():
    text = (
        "4. Customer Journey\n"
        "4. Customer Journey\n"
        "4. Customer Journey Mega Add-ons Customer Journey\n"
        "Step 1: Open app"
    )

    cleaned = sanitize_chunk_text(text, "4. Customer Journey")

    assert cleaned == "4. Customer Journey Mega Add-ons Customer Journey\nStep 1: Open app"
