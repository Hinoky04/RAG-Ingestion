from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from sourcecode.parsers.docx_parser import DOCXParser
from sourcecode.processing.chunker import chunk_document
from sourcecode.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


def add_hyperlink(paragraph, label: str, url: str) -> None:
    relationship_id = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = label
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def test_docx_parser_preserves_body_order_links_and_table_boundaries(tmp_path: Path):
    path = tmp_path / "article.docx"
    document = Document()
    document.add_paragraph("Article title")
    first_table = document.add_table(rows=1, cols=2)
    first_table.cell(0, 0).text = "Plan"
    link_paragraph = first_table.cell(0, 1).paragraphs[0]
    link_paragraph.add_run(
        "Detailed plan information for eligible subscribers, including activation rules, service coverage, "
        "billing conditions, availability requirements, renewal behaviour, support channels, and account guidance. "
    )
    add_hyperlink(link_paragraph, "Learn more", "https://example.com/plan")
    document.add_paragraph("Closing note with enough context to remain associated with the first table during chunking.")
    second_table = document.add_table(rows=1, cols=2)
    second_table.cell(0, 0).text = "Support"
    second_table.cell(0, 1).text = (
        "Contact the help desk for account support, billing questions, roaming advice, service troubleshooting, "
        "follow-up guidance for eligible subscribers, account verification, product eligibility, and plan changes."
    )
    document.save(path)

    record = DocumentRecord(source_path=str(path), file_name=path.name, file_type="docx", checksum="test")
    parsed = DOCXParser().parse(record)

    assert [block.block_type for block in parsed.blocks] == [
        BlockType.TEXT,
        BlockType.TABLE,
        BlockType.TEXT,
        BlockType.TABLE,
    ]
    assert "https://example.com/plan" in parsed.blocks[1].text
    assert parsed.blocks[1].metadata["hyperlinks"] == [{"text": "Learn more", "url": "https://example.com/plan"}]

    chunks = chunk_document(parsed)
    assert len(chunks) == 2
    assert chunks[0].section_path.startswith("Plan:")
    assert "Article title" in chunks[0].text
    assert chunks[1].section_path.startswith("Support:")


def test_docx_parser_includes_nested_table_content(tmp_path: Path):
    path = tmp_path / "nested-table.docx"
    document = Document()
    section = document.add_table(rows=1, cols=2)
    section.cell(0, 0).text = "Offering details"
    section.cell(0, 1).text = "Available add-ons"
    offers = section.cell(0, 1).add_table(rows=2, cols=2)
    offers.cell(0, 0).text = "Offer"
    offers.cell(0, 1).text = "Price"
    offers.cell(1, 0).text = "Disney+ Basic + 5GB"
    offers.cell(1, 1).text = "RM12.90/month"
    document.save(path)

    record = DocumentRecord(source_path=str(path), file_name=path.name, file_type="docx", checksum="test")
    parsed = DOCXParser().parse(record)

    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].block_type == BlockType.TABLE
    assert "Disney+ Basic + 5GB: RM12.90/month" in parsed.blocks[0].text


def test_chunker_splits_large_price_table_by_product():
    header = "Offer | Plans Eligibility | Price"
    rows = [header]
    for product in range(20):
        for plan in range(4):
            rows.append(f"Product {product} | CD{60 + plan} | RM{plan + 1}.90/month RRP:RM29.90")

    document = CanonicalDocument(
        document_id="doc-price-table",
        document_type="document",
        source_path="price-table.docx",
        file_name="price-table.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-price-table",
                block_type=BlockType.HEADING,
                text="Product details",
                source_path="price-table.docx",
                parser_name="python-docx",
            ),
            ParsedBlock(
                document_id="doc-price-table",
                block_type=BlockType.TABLE,
                text="\n".join(rows),
                source_path="price-table.docx",
                parser_name="python-docx",
            ),
            ParsedBlock(
                document_id="doc-price-table",
                block_type=BlockType.HEADING,
                text="Eligibility",
                source_path="price-table.docx",
                parser_name="python-docx",
            ),
            ParsedBlock(
                document_id="doc-price-table",
                block_type=BlockType.HEADING,
                text="Support",
                source_path="price-table.docx",
                parser_name="python-docx",
            ),
        ],
    )

    chunks = chunk_document(document)
    product_chunks = [chunk for chunk in chunks if chunk.metadata.get("table_chunking") == "product_group"]

    assert len(product_chunks) == 20
    first = product_chunks[0]
    assert first.section_path == "Product details - Product 0"
    assert header in first.text
    assert "Product: Product 0" in first.text
    assert "CD60" in first.text and "CD63" in first.text
    assert "Product 1" not in first.text
