from src.parsers.pdf_parser import PDFLine, PDFParser
from src.representation.schemas import BlockType, ParsedBlock


def test_pdf_parser_does_not_treat_numeric_table_labels_as_major_headings():
    parser = PDFParser()
    block_type, heading_level, metadata = parser.classify_line(
        PDFLine(
            text="3 Lines",
            page_number=1,
            line_number=1,
            y0=0,
            y1=10,
            page_height=1000,
            max_font_size=12,
            avg_font_size=12,
            is_bold=False,
        ),
        body_font_size=11,
    )

    assert block_type == BlockType.TEXT
    assert heading_level is None
    assert metadata["structure_hint"] == "numeric_table_label"


def test_pdf_parser_merges_fragmented_words_without_spaces():
    parser = PDFParser()
    merged = parser.merge_blocks(
        [
            ParsedBlock(document_id="doc", block_type=BlockType.TEXT, text="Offeri", source_path="x.pdf", parser_name="pymupdf"),
            ParsedBlock(document_id="doc", block_type=BlockType.TEXT, text="ng", source_path="x.pdf", parser_name="pymupdf"),
            ParsedBlock(document_id="doc", block_type=BlockType.TEXT, text="Detail", source_path="x.pdf", parser_name="pymupdf"),
            ParsedBlock(document_id="doc", block_type=BlockType.TEXT, text="s", source_path="x.pdf", parser_name="pymupdf"),
        ],
        separator=" ",
        merge_kind="paragraph_lines",
    )

    assert merged.text == "Offering Details"
