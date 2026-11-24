from sourcecode.parsers.pdf_parser import PDFLine, PDFParser
from sourcecode.representation.schemas import BlockType, ParsedBlock


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


def test_pdf_parser_recognizes_a_two_column_layout_row_as_a_table():
    parser = PDFParser()

    block_type, _, metadata = parser.classify_line(
        PDFLine("Charging Block | RM7.80", 1, 1, 0, 10, 1000, 12, 12, False),
        body_font_size=11,
    )

    assert block_type == BlockType.TABLE
    assert metadata["possible_table"] is True


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


def test_pdf_parser_keeps_a_one_off_left_margin_label_as_source_evidence():
    parser = PDFParser()
    label = ParsedBlock(
        document_id="doc", block_type=BlockType.TEXT, text="USP", source_path="x.pdf", parser_name="pymupdf",
        metadata={"x0": 20, "line_width": 30},
    )

    rebuilt = parser.rebuild_flow_blocks([label])

    assert rebuilt == [label]


def test_pdf_parser_joins_wrapped_table_cells_before_rebuilding_the_row():
    parser = PDFParser()
    lines = [
        PDFLine("Essential", 1, 1, 10, 20, 1000, 12, 12, True, x0=100, x1=160),
        PDFLine("Essential", 1, 2, 10, 20, 1000, 12, 12, True, x0=200, x1=260),
        PDFLine("Premium", 1, 3, 10, 20, 1000, 12, 12, True, x0=300, x1=360),
        PDFLine("(Retail only)", 1, 4, 22, 32, 1000, 12, 12, False, x0=100, x1=170),
    ]

    stitched = parser.stitch_vertical_fragments(lines)
    rows = parser.merge_same_row_fragments(stitched)

    assert len(rows) == 1
    assert rows[0].text == "Essential (Retail only) | Essential | Premium"


def test_pdf_parser_keeps_a_numeric_model_hyphen_when_joining_wrapped_text():
    parser = PDFParser()

    assert parser.join_vertical_text("H162-", "383") == "H162-383"


def test_pdf_parser_joins_wrapped_centered_cell_text_with_a_small_x_offset():
    parser = PDFParser()
    previous = PDFLine("Unlimite", 1, 1, 10, 20, 1000, 12, 12, False, x0=200, x1=240)
    current = PDFLine("d", 1, 2, 21, 31, 1000, 12, 12, False, x0=218, x1=225)

    assert parser.can_stitch_vertical(previous, current)




def test_pdf_parser_does_not_join_adjacent_table_rows_in_the_same_column():
    parser = PDFParser()
    lines = [
        PDFLine("Tier 1", 1, 1, 10, 20, 1000, 12, 12, False, x0=100, x1=150),
        PDFLine("RM0", 1, 2, 10, 20, 1000, 12, 12, False, x0=200, x1=240),
        PDFLine("Tier 2", 1, 3, 22, 32, 1000, 12, 12, False, x0=100, x1=150),
        PDFLine("RM7.80", 1, 4, 22, 32, 1000, 12, 12, False, x0=200, x1=250),
    ]

    stitched = parser.stitch_vertical_fragments(lines)

    assert [line.text for line in stitched] == ["Tier 1", "RM0", "Tier 2", "RM7.80"]


def test_pdf_parser_merges_short_parallel_header_rows_without_touching_prices():
    parser = PDFParser()
    first = PDFLine("Celcom | Celcom | Celcom", 1, 1, 10, 20, 1000, 12, 12, True, x0=10, x1=300)
    second = PDFLine("Digi | Digi | Digi", 1, 2, 21, 31, 1000, 12, 12, True, x0=10, x1=300)
    price = PDFLine("RM 80 | RM 100 | RM 120", 1, 3, 32, 42, 1000, 12, 12, False, x0=10, x1=300)

    merged = parser.merge_parallel_header_rows([first, second, price])

    assert [line.text for line in merged] == ["Celcom Digi | Celcom Digi | Celcom Digi", "RM 80 | RM 100 | RM 120"]


def test_pdf_parser_selects_only_a_dense_multi_column_vector_grid():
    parser = PDFParser()
    rows = [
        ["Section title", None, None],
        [None, "Offer", "Eligibility", "Price"],
        [None, "Basic", "CD60", "RM12.90"],
        [None, None, "CD120", "RM3.90"],
    ]

    assert parser.vector_grid_start(rows) == 1
    assert parser.has_reliable_grid_content(rows[1:])
    assert parser.vector_grid_start([["Label", "Value"], ["A", "B"]]) is None


def test_pdf_parser_recognizes_a_sparse_feature_matrix_without_prices():
    parser = PDFParser()
    rows = [
        ["Function", "iOS", "Android", "How it protects"],
        ["SMS protection", "", "", "Filters suspicious messages"],
        ["Browser protection", "", "", "Blocks unsafe websites"],
        ["Privacy VPN", "", "", "Encrypts traffic"],
    ]

    assert parser.vector_grid_start(rows) == 0
    assert parser.has_reliable_grid_content(rows)


def test_pdf_parser_recognizes_a_dense_plan_matrix_without_prices():
    parser = PDFParser()
    rows = [
        ["Plan", "Plan 80", "Plan 100", "Plan 120"],
        ["Add-ons", "Available", "Available", "Available"],
        ["Contract", "12 months", "12 months", "24 months"],
    ]

    assert parser.has_reliable_grid_content(rows)


def test_pdf_parser_accepts_a_sparse_symbol_matrix_header_only_when_its_grid_is_explicit():
    parser = PDFParser()
    rows = [
        ["Type", "Sports Bundle", "Asian Bundle", "Asian & Sports Bundle", "Family Bundle"],
        ["Postpaid", None, None, None, None],
    ]

    assert parser.has_sufficient_grid_rows(rows, [5, 1])
    assert parser.has_reliable_grid_content(rows)
    assert not parser.is_symbol_matrix_header([["Type", "Plan A", "Plan B"], ["Postpaid", None, None]])
    assert parser.normalize_symbol_matrix_header_cell("Sports\nBundle\nsooka") == "Sports Bundle sooka"


def test_pdf_parser_restores_wrapped_word_fragments_inside_vector_table_cells():
    parser = PDFParser()

    assert parser.normalize_table_cell("Celcom Digi Postpai\nd 5G") == "Celcom Digi Postpaid 5G"
    assert parser.normalize_table_cell("Brovi H162-\n383") == "Brovi H162-383"
    assert parser.normalize_table_cell("Monthly\nFee") == "Monthly Fee"
    assert parser.normalize_table_cell("Use AI\nto analyze SMS") == "Use AI to analyze SMS"
    assert parser.normalize_table_cell("CelcomD\nigi Postpaid") == "CelcomDigi Postpaid"
    assert parser.normalize_table_cell("Suppleme\nntary line") == "Supplementary line"
    assert parser.normalize_table_cell("Calls\nare managed") == "Calls are managed"
    assert parser.normalize_table_cell("Add-\nOns") == "Add-Ons"
    assert parser.normalize_table_cell("Viu Premium (with\nPMJ)") == "Viu Premium (with PMJ)"


def test_pdf_parser_keeps_numbered_and_lettered_steps_as_separate_list_items():
    parser = PDFParser()
    first = ParsedBlock(
        document_id="doc", block_type=BlockType.LIST_ITEM, text="1. Open the app.", source_path="x.pdf",
        parser_name="pymupdf", metadata={"x0": 100, "y1": 20},
    )
    continuation = ParsedBlock(
        document_id="doc", block_type=BlockType.TEXT, text="Choose Roaming.", source_path="x.pdf",
        parser_name="pymupdf", metadata={"x0": 120, "y0": 21, "y1": 31},
    )
    letter = ParsedBlock(
        document_id="doc", block_type=BlockType.LIST_ITEM, text="a. Select a pass.", source_path="x.pdf",
        parser_name="pymupdf", metadata={"x0": 120, "y0": 35, "y1": 45},
    )

    rebuilt = parser.rebuild_flow_blocks([first, continuation, letter])

    assert [block.text for block in rebuilt] == ["1. Open the app. Choose Roaming.", "a. Select a pass."]


def test_pdf_parser_distinguishes_a_short_numbered_heading_from_a_wrapped_step():
    parser = PDFParser()
    heading = PDFLine("4. Customer Journey (current journey / campaign only)", 1, 1, 0, 10, 100, 12, 12, True)
    step = PDFLine("1. Targeted customers will receive an SMS to check out the offer", 1, 2, 12, 22, 100, 12, 12, True)

    assert parser.classify_line(heading, 11)[0] == BlockType.HEADING
    assert parser.classify_line(step, 11)[0] == BlockType.LIST_ITEM


def test_pdf_parser_keeps_an_unbold_short_numbered_step_as_a_list_item():
    parser = PDFParser()
    step = PDFLine("2. Select Freedom Add-on", 1, 1, 0, 10, 100, 12, 12, False)

    assert parser.classify_line(step, 11)[0] == BlockType.LIST_ITEM


def test_pdf_parser_recognizes_a_long_bold_numbered_section_with_an_en_dash():
    parser = PDFParser()
    heading = PDFLine(
        "3. Base Rates – Voice Calls, SMS and MMS", 1, 1, 0, 10, 100, 12, 12, True
    )

    assert parser.classify_line(heading, 11)[0] == BlockType.HEADING


def test_pdf_parser_promotes_a_standalone_section_title_embedded_in_table_text():
    parser = PDFParser()
    table = ParsedBlock(
        document_id="doc", block_type=BlockType.TABLE,
        text="Channels | App\n2. Product Details\nPlan | Basic | Premium",
        source_path="x.pdf", parser_name="pymupdf",
    )

    rebuilt = parser.split_embedded_section_titles([table])

    assert [block.text for block in rebuilt] == ["Channels | App", "2. Product Details", "Plan | Basic | Premium"]
    assert rebuilt[1].block_type == BlockType.HEADING
    assert rebuilt[1].heading_level == 1


def test_pdf_parser_splits_a_field_label_from_an_inline_numbered_section_title():
    parser = PDFParser()
    block = ParsedBlock(
        document_id="doc", block_type=BlockType.HEADING,
        text="Visuals 3. Customer-Facing Information FAQs", heading_level=2,
        source_path="x.pdf", parser_name="pymupdf", metadata={"bold": True},
    )

    rebuilt = parser.split_inline_section_titles([block])

    assert [item.text for item in rebuilt] == ["Visuals", "3. Customer-Facing Information FAQs"]
    assert rebuilt[1].block_type == BlockType.HEADING
    assert rebuilt[1].heading_level == 1


def test_pdf_parser_promotes_a_bold_margin_section_left_as_a_list_item():
    parser = PDFParser()
    item = ParsedBlock(
        document_id="doc", block_type=BlockType.LIST_ITEM,
        text="5. Customer Communications (Active)", source_path="x.pdf",
        parser_name="pymupdf", metadata={"bold": True, "x0": 72.0},
    )

    rebuilt = parser.promote_margin_numbered_sections([item])

    assert rebuilt[0].block_type == BlockType.HEADING
    assert rebuilt[0].heading_level == 1


def test_pdf_parser_repairs_a_numbered_title_wrapped_into_the_next_table_block():
    parser = PDFParser()
    title = ParsedBlock(
        document_id="doc", block_type=BlockType.LIST_ITEM,
        text="8. Historical Communications (retained for reference", source_path="x.pdf",
        parser_name="pymupdf", metadata={"bold": True, "x0": 72.0},
    )
    table = ParsedBlock(
        document_id="doc", block_type=BlockType.TABLE,
        text="only) Inactive Comms | NA", source_path="x.pdf", parser_name="pymupdf",
    )

    rebuilt = parser.repair_wrapped_numbered_section_titles([title, table])

    assert rebuilt[0].block_type == BlockType.HEADING
    assert rebuilt[0].text == "8. Historical Communications (retained for reference only)"
    assert rebuilt[1].text == "Inactive Comms | NA"
