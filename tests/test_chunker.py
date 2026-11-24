from sourcecode.processing.chunker import ChunkDraft, chunk_document, sanitize_chunk_text
from sourcecode.processing.docx.table_context import expand_explicit_symbol_legend, explicit_symbol_legend, nested_table_notes_by_path
from sourcecode.processing.docx.table_strategies import split_hierarchical_row_matrix, split_two_column_parallel_description
from sourcecode.processing.docx.table_utils import table_rows_to_text
from sourcecode.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def test_explicit_table_symbol_legend_makes_markers_searchable_without_guessing():
    block = ParsedBlock(
        document_id="doc-symbols",
        block_type=BlockType.TABLE,
        text=(
            "Eligibility matrix\n"
            "1. ✅ Eligible\n"
            "2. ✖️ Not eligible\n"
            "3. 🔵 Eligible with replacement of existing subscription"
        ),
        source_path="symbols.docx",
        parser_name="python-docx",
    )

    legend = explicit_symbol_legend(block)
    output = expand_explicit_symbol_legend(
        [("Eligibility", "Plan A: ✖️\nPlan B: 🔵\nPlan C: ✅", {})],
        legend,
    )

    assert output[0][1] == "Plan A: ✖️ Not eligible\nPlan B: 🔵 Eligible with replacement of existing subscription\nPlan C: ✅ Eligible"
    assert output[0][2]["table_symbol_legend"] == "explicit"


def test_nested_table_notes_stay_with_the_preceding_table_in_the_same_parent_cell():
    block = ParsedBlock(
        document_id="doc-notes",
        block_type=BlockType.TABLE,
        text="Eligibility",
        source_path="notes.docx",
        parser_name="python-docx",
        metadata={
            "table_fragments": [
                {"kind": "nested_table", "table_path": "root.table1", "cell_path": "root.r1c1", "xml_ordinal": 1},
                {"kind": "paragraph", "cell_path": "root.r1c1", "xml_ordinal": 2, "text": "Notes:"},
                {"kind": "paragraph", "cell_path": "root.r1c1", "xml_ordinal": 3, "text": "First table rule."},
                {"kind": "nested_table", "table_path": "root.table2", "cell_path": "root.r1c1", "xml_ordinal": 4},
                {"kind": "paragraph", "cell_path": "root.r1c1", "xml_ordinal": 5, "text": "Notes:"},
                {"kind": "paragraph", "cell_path": "root.r1c1", "xml_ordinal": 6, "text": "Second table rule."},
            ]
        },
    )

    annotations = nested_table_notes_by_path(block)

    assert annotations == {
        "root.table1": ["Notes:", "First table rule."],
        "root.table2": ["Notes:", "Second table rule."],
    }


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

    assert len(chunks) == 2
    assert chunks[0].section_path == "1. First section"
    assert "Document title" in chunks[0].text
    assert "Key details" in chunks[0].text
    assert chunks[1].section_path == "2. Second section"
    assert "More details" in chunks[1].text


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
        "Page unknown - Plan 80",
        "Page unknown - Plan 100",
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
        "Page unknown - Daily | RM5 | Unlimited 18Mbps",
        "Page unknown - Weekly | RM12 | 20GB",
    ]
    assert chunks[0].metadata["table_chunking"] == "structured_offer_row"
    assert "Category: Daily" in chunks[0].text
    assert "Price: RM12" in chunks[1].text


def test_docx_chunker_keeps_merged_offer_groups_with_their_eligibility():
    document = CanonicalDocument(
        document_id="doc-merged-offers",
        document_type="document",
        source_path="merged-offers.docx",
        file_name="merged-offers.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-merged-offers",
                block_type=BlockType.TABLE,
                text="Offering details",
                source_path="merged-offers.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {"depth": 0, "rows": [["Product Details", "Product Details"]]},
                        {
                            "depth": 1,
                            "rows": [
                                ["Freedom Add-Ons", "Offer", "Plan Eligibility"],
                                ["Roaming Internet", "5GB + 15 Minutes Monthly", "CD120 & above"],
                                ["IDD", "30 minutes", "CD60 SE - CD100"],
                                ["IDD", "60 minutes", "CD120 & above"],
                                ["Extra Internet", "20GB Monthly", "CD45 SE"],
                                ["Extra Internet", "50GB Monthly", "CD60 SE"],
                            ],
                        },
                    ]
                },
            )
        ],
    )

    chunks = chunk_document(document)
    idd = next(chunk for chunk in chunks if chunk.section_path.endswith("IDD"))
    extra_internet = next(chunk for chunk in chunks if chunk.section_path.endswith("Extra Internet"))

    assert idd.metadata["table_chunking"] == "grouped_three_column_rows"
    assert "Offer: 30 minutes" in idd.text
    assert "Plan Eligibility: CD60 SE - CD100" in idd.text
    assert "Offer: 60 minutes" in idd.text
    assert "Offer: 20GB Monthly" in extra_internet.text
    assert "Offer: 50GB Monthly" in extra_internet.text


def test_sanitize_chunk_text_removes_repeated_section_lines():
    text = (
        "4. Customer Journey\n"
        "4. Customer Journey\n"
        "4. Customer Journey Mega Add-ons Customer Journey\n"
        "Step 1: Open app"
    )

    cleaned = sanitize_chunk_text(text, "4. Customer Journey")

    assert cleaned == "4. Customer Journey Mega Add-ons Customer Journey\nStep 1: Open app"


def test_sanitize_chunk_text_removes_immediately_repeated_numbered_list_only():
    text = (
        "Subscriptions:\n"
        "- 1. Non-contractual Monthly Add-on\n"
        "- 2. Contractual Monthly Add-on\n"
        "- 1. Non-contractual Monthly Add-on\n"
        "- 2. Contractual Monthly Add-on"
    )

    cleaned = sanitize_chunk_text(text)

    assert cleaned == (
        "Subscriptions:\n"
        "- 1. Non-contractual Monthly Add-on\n"
        "- 2. Contractual Monthly Add-on"
    )


def test_chunker_collapses_colon_variant_of_merged_table_heading():
    document = CanonicalDocument(
        document_id="doc-merged-heading",
        document_type="document",
        source_path="merged.docx",
        file_name="merged.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-merged-heading",
                block_type=BlockType.TABLE,
                text="MobileSHIELD",
                source_path="merged.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {
                            "depth": 0,
                            "rows": [
                                ["What MobileSHIELD can do", "What MobileSHIELD can do:"],
                                [
                                    "Subscription",
                                    "Available from April with multi-license plans for customers who manage devices in the MobileSHIELD app.",
                                ],
                            ],
                        },
                        {"depth": 1, "rows": [["Plan", "RM10", "RM15"]]},
                    ]
                },
            )
        ],
    )

    overview = next(chunk for chunk in chunk_document(document) if chunk.metadata["table_chunking"] == "table_overview")

    assert overview.text.count("What MobileSHIELD can do") == 1


def test_table_rows_to_text_collapses_multi_column_merged_heading():
    text = table_rows_to_text([["4. Customer Journey", "4. Customer Journey:", "4. Customer Journey", "4. Customer Journey"]])

    assert text == "4. Customer Journey"


def test_table_rows_to_text_removes_repeated_merged_label_before_its_detail_row():
    text = table_rows_to_text([["Customer Journey"], ["Customer Journey", "Step 1: Open the app"]])

    assert text == "Customer Journey: Step 1: Open the app"


def test_parallel_two_column_description_keeps_each_field_with_its_own_bullets():
    output = split_two_column_parallel_description(
        ChunkDraft(section_path="Fee"),
        [
            ["Subscription Fee", "Service Request Fee"],
            ["Monthly charge\n- Billed on the next invoice", "One-time charge\n- Paid when requesting a repair"],
        ],
        2,
    )

    assert output is not None
    _, text, metadata = output[0]
    assert "Subscription Fee:" in text
    assert "- Billed on the next invoice" in text
    assert "Service Request Fee:" in text
    assert "- Paid when requesting a repair" in text
    assert metadata["table_chunking"] == "two_column_parallel_description"


def test_hierarchical_row_matrix_keeps_price_fields_on_each_record():
    output = split_hierarchical_row_matrix(
        ChunkDraft(section_path="PhoneFIX"),
        [
            ["Device price tier", "PhoneFIX", "PhoneFIX", "PhoneFIX"],
            ["Device price tier", "Repair Only", "Repair Only", "Repair Only"],
            ["Device price tier", "Subscription Fee", "Subscription Fee", "Service Request Fee"],
            ["Device price tier", "Promo Price", "Monthly Price", "Service Request Fee"],
            ["RM0-RM500", "1", "3", "30"],
            ["RM501-RM1,000", "1", "5", "50"],
            ["RM1,001-RM1,500", "1", "6", "100"],
            ["RM1,501-RM3,000", "1", "10", "200"],
        ],
        3,
    )

    assert output is not None
    _, text, metadata = output[0]
    assert "RM1,501-RM3,000" in text
    assert "Promo Price: 1" in text
    assert "Monthly Price: 10" in text
    assert "Service Request Fee: 200" in text
    assert metadata["table_chunking"] == "hierarchical_row_matrix"


def test_chunker_keeps_number_and_country_pairs_in_their_original_order():
    document = CanonicalDocument(
        document_id="doc-country-list",
        document_type="document",
        source_path="countries.docx",
        file_name="countries.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-country-list",
                block_type=BlockType.TABLE,
                text="Country list",
                source_path="countries.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {
                            "depth": 1,
                            "rows": [
                                ["Monthly 30GB", "Monthly 30GB", "Monthly 80GB", "Monthly 80GB", "Monthly 80GB", "Monthly 80GB", "Monthly 80GB", "Monthly 80GB"],
                                ["No", "Country List", "No", "Country List", "No", "Country List", "No", "Country List"],
                                ["1", "Singapore", "1", "Albania", "31", "India", "61", "Saudi Arabia"],
                                ["2", "Indonesia", "2", "Armenia", "32", "Indonesia", "62", "Serbia"],
                                ["3", "Thailand", "3", "Australia", "33", "Ireland", "63", "Singapore"],
                            ],
                        }
                    ]
                },
            )
        ],
    )

    chunks = chunk_document(document)

    monthly_30 = next(chunk for chunk in chunks if chunk.section_path.endswith("Monthly 30GB"))
    monthly_80 = next(chunk for chunk in chunks if chunk.section_path.endswith("Monthly 80GB"))
    assert "1. Singapore" in monthly_30.text
    assert "2. Indonesia" in monthly_30.text
    assert "1. Albania" in monthly_80.text
    assert "31. India" in monthly_80.text
    assert "Singapore. 1" not in monthly_30.text


def test_chunker_inlines_tiny_nested_detail_table_into_its_parent_field():
    document = CanonicalDocument(
        document_id="doc-nested-price",
        document_type="document",
        source_path="price.docx",
        file_name="price.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-nested-price",
                block_type=BlockType.TABLE,
                text="Product details",
                source_path="price.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {"depth": 0, "rows": [["Product Details", "Product Details"]]},
                        {
                            "depth": 1,
                            "rows": [
                                ["Price", "Effective immediately"],
                                ["Eligible devices", "Android\niOS"],
                            ],
                        },
                        {
                            "depth": 2,
                            "rows": [
                                ["Promotional Price", "Normal Price"],
                                ["RM1 for first month", "RM3 subsequent months"],
                            ],
                        },
                    ],
                    "table_fragments": [
                        {
                            "kind": "nested_table",
                            "table_path": "root.r1c2.table1",
                            "parent_table_path": "root",
                            "cell_path": "root.r1c2",
                        },
                        {
                            "kind": "nested_table",
                            "table_path": "root.r1c2.table1.r1c2.table1",
                            "parent_table_path": "root.r1c2.table1",
                            "cell_path": "root.r1c2.table1.r1c2",
                        },
                    ],
                },
            )
        ],
    )

    chunks = chunk_document(document)

    price_chunk = next(chunk for chunk in chunks if "Effective immediately" in chunk.text)
    assert "Promotional Price: RM1 for first month" in price_chunk.text
    assert "Normal Price: RM3 subsequent months" in price_chunk.text
    assert "Eligible devices:\n- Android\n- iOS" in price_chunk.text
    assert not any(chunk.section_path.endswith("Table 2") for chunk in chunks)


def test_chunker_keeps_cross_column_mapping_rows_together_in_small_windows():
    document = CanonicalDocument(
        document_id="doc-plan-mapping",
        document_type="document",
        source_path="plans.docx",
        file_name="plans.docx",
        blocks=[
            ParsedBlock(
                document_id="doc-plan-mapping",
                block_type=BlockType.TABLE,
                text="Plan mapping",
                source_path="plans.docx",
                parser_name="python-docx",
                metadata={
                    "table_structures": [
                        {
                            "depth": 1,
                            "rows": [
                                ["CelcomDigi Plans", "Celcom Plans", "Digi Plans"],
                                ["CD 30", "XPAX 28", "Digi 40"],
                                ["CD 40", "XPAX 40", "Digi 60"],
                                ["CD 50", "XPAX 60", "Digi 60 DS"],
                                ["CD 60", "XPAX Unlimited", "Digi 60S"],
                                ["CD 80", "XPAX Basic", "Digi 90"],
                                ["CD 100", "MEGA", "Digi 120"],
                                ["CD 120", "MEGA 80", "Digi 150"],
                            ],
                        }
                    ]
                },
            )
        ],
    )

    chunks = chunk_document(document)

    assert len(chunks) == 2
    assert all(chunk.metadata["table_chunking"] == "row_mapping_window" for chunk in chunks)
    assert "CelcomDigi Plans: CD 30 | Celcom Plans: XPAX 28 | Digi Plans: Digi 40" in chunks[0].text
    assert "CelcomDigi Plans: CD 100 | Celcom Plans: MEGA | Digi Plans: Digi 120" in chunks[1].text
