from src.representation.markdown_builder import build_markdown
from src.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def test_markdown_builder_preserves_table_rows_in_a_fenced_block():
    table = ParsedBlock(
        document_id="doc-table",
        block_type=BlockType.TABLE,
        text="Offer | Price\nPrime Video | RM13.00/month",
        source_path="article.docx",
        parser_name="python-docx",
    )
    document = CanonicalDocument(
        document_id="doc-table",
        source_path="article.docx",
        file_name="article.docx",
        blocks=[table],
    )

    markdown = build_markdown(document)

    assert "```text\nOffer | Price\nPrime Video | RM13.00/month\n```" in markdown
