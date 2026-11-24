from sourcecode.processing.chunker import chunk_document
from sourcecode.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def block(kind: BlockType, text: str, level: int | None = None, page: int = 1) -> ParsedBlock:
    return ParsedBlock(
        document_id="pdf-context", block_type=kind, text=text, heading_level=level,
        page_number=page, source_path="context.pdf", parser_name="pymupdf",
    )


def test_pdf_context_chunker_attaches_a_short_title_to_first_real_section():
    document = CanonicalDocument(
        document_id="pdf-context", source_path="context.pdf", file_name="context.pdf",
        blocks=[
            block(BlockType.HEADING, "Product guide", 2),
            block(BlockType.HEADING, "1. Eligibility", 1),
            block(BlockType.HEADING, "Who can apply", 2),
            block(BlockType.TEXT, "Eligible customers may apply through the app with a valid active service."),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].section_path == "1. Eligibility"
    assert "Product guide" in chunks[0].text
    assert "Who can apply" in chunks[0].text
    assert chunks[0].metadata["chunking_strategy"] == "pdf_context_first_v1"


def test_pdf_context_chunker_does_not_attach_an_orphan_heading_to_the_next_section():
    document = CanonicalDocument(
        document_id="pdf-orphan", source_path="orphan.pdf", file_name="orphan.pdf",
        blocks=[
            block(BlockType.HEADING, "5. Free Basic Internet", 1),
            block(BlockType.HEADING, "6. Eligibility", 1),
            block(BlockType.TEXT, "Eligible customers receive the included internet allocation after activation."),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].section_path == "6. Eligibility"
    assert "5. Free Basic Internet" not in chunks[0].text


def test_pdf_context_chunker_omits_a_final_title_only_section():
    document = CanonicalDocument(
        document_id="pdf-final-orphan", source_path="final-orphan.pdf", file_name="final-orphan.pdf",
        blocks=[
            block(BlockType.HEADING, "7. Reference", 1),
            block(BlockType.TEXT, "Use the published support guide for the current policy."),
            block(BlockType.HEADING, "8. Historical Communications", 1),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert "8. Historical Communications" not in chunks[0].text


def test_pdf_context_chunker_splits_a_large_table_only_between_rows_and_repeats_header():
    header = "Plan | Eligibility | Price"
    rows = [header, *[f"Plan {index} | Eligible customer {index} | RM{index}" for index in range(40)]]
    document = CanonicalDocument(
        document_id="pdf-table", source_path="table.pdf", file_name="table.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Pricing", 1),
            block(BlockType.TABLE, "\n".join(rows)),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) > 1
    assert all(chunk.text.startswith("1. Pricing") for chunk in chunks)
    assert all(header in chunk.text for chunk in chunks)
    assert all(chunk.metadata["contains_table"] == "true" for chunk in chunks)


def test_pdf_context_chunker_repeats_a_late_multi_level_header_for_large_country_table():
    header = [
        "List of destinations:",
        "Monthly 30GB Pass | Monthly 80GB Pass",
        "No | Country List | No | Country List",
    ]
    rows = [f"{index} | Country {index} | {index + 40} | Other Country {index}" for index in range(1, 70)]
    document = CanonicalDocument(
        document_id="pdf-country-table", source_path="country-table.pdf", file_name="country-table.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Product Details", 1),
            block(BlockType.TABLE, "\n".join([
                "Hotspot | Yes",
                "Roaming Calls | Included",
                *header,
                *rows,
            ])),
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) > 1
    assert all("Monthly 30GB Pass | Monthly 80GB Pass" in chunk.text for chunk in chunks[1:])
    assert all("No | Country List | No | Country List" in chunk.text for chunk in chunks[1:])


def test_pdf_context_chunker_keeps_an_open_list_phrase_with_its_following_label():
    document = CanonicalDocument(
        document_id="pdf-open-phrase", source_path="open-phrase.pdf", file_name="open-phrase.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Restrictions", 1),
            block(BlockType.TEXT, "Supporting context " * 220),
            block(BlockType.HEADING, "Non-eligible device", 2),
            block(BlockType.LIST_ITEM, "• Roaming services are not available in"),
            block(BlockType.HEADING, "Thailand", 2),
            block(BlockType.TEXT, "Pattani and Yala."),
        ],
    )

    chunks = chunk_document(document)

    restriction = next(chunk for chunk in chunks if "Thailand" in chunk.text)
    assert "Roaming services are not available in" in restriction.text


def test_pdf_context_chunker_repeats_an_explicit_header_for_a_following_table_continuation():
    document = CanonicalDocument(
        document_id="pdf-table-continuation", source_path="continuation.pdf", file_name="continuation.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Offers", 1),
            block(BlockType.TABLE, "Context | Value\nCategory | Price | Quota | Validity"),
            block(BlockType.TABLE, "| Hourly | RM1 | 1GB | 1 Hour\n| Daily | RM3 | 3GB | 1 Day"),
        ],
    )

    chunks = chunk_document(document)

    continuation = next(chunk for chunk in chunks if "Hourly" in chunk.text)
    assert "Category | Price | Quota | Validity" in continuation.text


def test_pdf_context_chunker_repeats_a_type_header_for_status_matrix_continuation():
    document = CanonicalDocument(
        document_id="pdf-eligibility-continuation", source_path="eligibility.pdf", file_name="eligibility.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Eligibility", 1),
            block(BlockType.TABLE, "Type | Sports Bundle | Asian Bundle | Family Bundle\nPostpaid"),
            block(BlockType.TABLE, "Prepaid\nCD Plan 80 | ✅ | ✅ | ✅\nCD Plan 100 | ✖ | ✅ | ✅"),
        ],
    )

    chunks = chunk_document(document)

    continuation = next(chunk for chunk in chunks if "CD Plan 80" in chunk.text)
    assert "Type | Sports Bundle | Asian Bundle | Family Bundle" in continuation.text


def test_pdf_context_chunker_repeats_a_table_record_identity_for_a_new_chunk():
    filler = " ".join(["detail"] * 252)
    document = CanonicalDocument(
        document_id="pdf-table-record-context", source_path="record-context.pdf", file_name="record-context.pdf",
        blocks=[
            block(BlockType.HEADING, "1. Offers", 1),
            block(BlockType.TABLE, f"Bundle | Sports Bundle\nDetails | {filler}"),
            block(BlockType.TABLE, "Access | Premium\nPrice | RM59.90"),
        ],
    )

    chunks = chunk_document(document)

    continuation = next(chunk for chunk in chunks if "Access | Premium" in chunk.text)
    assert "Bundle | Sports Bundle" in continuation.text
