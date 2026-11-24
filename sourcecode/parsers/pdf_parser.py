"""Recover headings, rows, and reading order from positioned PDF text.

PDF pages do not provide dependable paragraph or table structure. Coordinates
and font details are kept until row and flow repair is finished. A false heading
here would split every later chunk in the wrong place, so uncertain lines stay
as ordinary text.
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import median

import fitz

from sourcecode.parsers.base_parser import BaseParser
from sourcecode.parsers.pdf_heuristics import (
    looks_like_list_item as is_list_item,
    looks_like_numbered_sentence as is_numbered_sentence,
    looks_like_numeric_table_label as is_numeric_table_label,
    looks_like_table_row as is_table_row,
    looks_like_transfer_code as is_transfer_code,
)
from sourcecode.parsers.pdf_models import PDFLine
from sourcecode.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


class PDFParser(BaseParser):
    """PyMuPDF parser tuned for the layouts represented in the project corpus."""

    parser_name = "pymupdf"
    parser_version = "v1.5"

    step_pattern = re.compile(r"^Step\s+\d+\s*:", re.IGNORECASE)
    # Use escaped dash here. It avoids encoding problem in this regex.
    section_pattern = re.compile(
        r"^\d+\.(?:\d+\.)*\s+[A-Z][A-Za-z0-9(),/&:.\-\u2013\u2014 ]{2,}$"
    )
    faq_pattern = re.compile(r"^Q\d*\.?\s+", re.IGNORECASE)
    ordered_list_pattern = re.compile(r"^(?:\d+|[a-z])\.\s+", re.IGNORECASE)
    common_short_words = frozenset({
        "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "if", "in",
        "is", "it", "no", "not", "of", "on", "only", "or", "plan", "that", "the", "then", "this", "to", "up",
        "via", "was", "we", "will", "with", "yes", "you",
    })

    def classify_line(self, line: PDFLine, body_font_size: float) -> tuple[BlockType, int | None, dict[str, object]]:
        metadata: dict[str, object] = {}
        stripped = line.text.strip()

        if line.is_table_grid or self.looks_like_table_row(stripped):
            metadata["possible_table"] = True
            return BlockType.TABLE, None, metadata

        if self.looks_like_numeric_table_label(stripped):
            metadata["structure_hint"] = "numeric_table_label"
            return BlockType.TEXT, None, metadata

        if self.step_pattern.match(stripped):
            metadata["structure_hint"] = "procedure_step"
            return BlockType.HEADING, 3, metadata

        if self.faq_pattern.match(stripped):
            metadata["structure_hint"] = "faq_question"
            return BlockType.HEADING, 3, metadata

        # Real section number is short. Long one is normally a procedure step.
        if self.looks_like_numbered_section_heading(line):
            depth = stripped.split(maxsplit=1)[0].rstrip(".").count(".") + 1
            metadata["structure_hint"] = "numbered_section"
            return BlockType.HEADING, min(depth, 4), metadata

        if self.ordered_list_pattern.match(stripped):
            metadata["structure_hint"] = "ordered_list_item"
            return BlockType.LIST_ITEM, None, metadata

        if self.looks_like_numbered_sentence(stripped):
            metadata["structure_hint"] = "ordered_list_item"
            return BlockType.LIST_ITEM, None, metadata

        if self.section_pattern.match(stripped):
            depth = stripped.split(maxsplit=1)[0].rstrip(".").count(".") + 1
            metadata["structure_hint"] = "numbered_section"
            return BlockType.HEADING, min(depth, 4), metadata

        if self.looks_like_short_heading(stripped):
            metadata["structure_hint"] = "short_heading"
            return BlockType.HEADING, 2, metadata

        if self.looks_like_styled_heading(stripped, line, body_font_size):
            metadata["structure_hint"] = "font_style"
            metadata["font_size"] = round(line.max_font_size, 2)
            metadata["body_font_size"] = round(body_font_size, 2)
            metadata["bold"] = line.is_bold
            return BlockType.HEADING, 2, metadata

        if self.looks_like_list_item(stripped):
            metadata["structure_hint"] = "list_item"
            return BlockType.LIST_ITEM, None, metadata

        return BlockType.TEXT, None, metadata

    def looks_like_numbered_section_heading(self, line: PDFLine) -> bool:
        text = line.text.strip()
        if not self.section_pattern.match(text):
            return False
        # Real section title is bold in these PDFs. Normal text like
        # "2. Select Freedom Add-on" is a step, not a new section.
        if not line.is_bold:
            return False
        has_descriptive_parenthesis = bool(re.search(r"\([^)]*\s[^)]*\)", text))
        return len(text.split()) <= 10 or has_descriptive_parenthesis

    def looks_like_embedded_section_title(self, text: str) -> bool:
        """Recognize a standalone section line extracted from a table block.

        Grid-cell text has no individual font evidence, but this path is only
        used for a full, pipe-free line inside an already extracted table.
        """
        if not self.section_pattern.match(text):
            return False
        has_descriptive_parenthesis = bool(re.search(r"\([^)]*\s[^)]*\)", text))
        return len(text.split()) <= 7 or has_descriptive_parenthesis

    def looks_like_short_heading(self, line: str) -> bool:
        if len(line) > 90 or len(line) < 4:
            return False
        if line.endswith((".", ",", ";", ":")):
            return False
        if self.looks_like_transfer_code(line):
            return False

        words = line.split()
        if len(words) > 10:
            return False

        starts_like_title = sum(word[:1].isupper() for word in words if word[:1].isalpha())
        return starts_like_title >= max(1, len(words) - 1)

    def looks_like_transfer_code(self, line: str) -> bool:
        return is_transfer_code(line)

    def looks_like_numeric_table_label(self, line: str) -> bool:
        return is_numeric_table_label(line)

    def looks_like_numbered_sentence(self, line: str) -> bool:
        return is_numbered_sentence(line)

    def looks_like_styled_heading(self, text: str, line: PDFLine, body_font_size: float) -> bool:
        if len(text) < 4 or len(text) > 120:
            return False
        if text.endswith((".", ",", ";")):
            return False
        if re.search(r"@|https?://|www\.", text, re.IGNORECASE):
            return False
        if text[:1].islower():
            return False
        if self.looks_like_transfer_code(text):
            return False

        words = text.split()
        if len(words) > 14:
            return False

        bigger_than_body = body_font_size > 0 and line.max_font_size >= body_font_size + 1.5
        bold_short_line = line.is_bold and len(words) <= 10
        title_like = sum(word[:1].isupper() for word in words if word[:1].isalpha()) >= max(1, len(words) // 2)
        return (bigger_than_body or bold_short_line) and title_like

    def looks_like_table_row(self, line: str) -> bool:
        return is_table_row(line)

    def looks_like_list_item(self, line: str) -> bool:
        return is_list_item(line)

    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        source_path = Path(record.source_path)
        blocks: list[ParsedBlock] = []

        with fitz.open(source_path) as document:
            lines = self.extract_lines(document)
            body_font_size = self.estimate_body_font_size(lines)
            margin_noise = self.find_repeated_margin_lines(lines)

            for line in lines:
                # Some headers use hidden wide/narrow spaces. Change to normal space.
                cleaned_line = re.sub(r"[\u00a0\u202f]", " ", line.text).strip()
                block_type, heading_level, metadata = self.classify_line(line, body_font_size)
                if block_type == BlockType.HEADING:
                    cleaned_line = self.clean_heading_text(cleaned_line)
                normalized = self.normalize_for_margin_check(cleaned_line)
                if normalized in margin_noise:
                    metadata["repeated_margin_noise"] = True

                metadata.update(
                    {
                        "source_format": "pdf",
                        "pymupdf_page_index": line.page_number - 1,
                        "line_number": line.line_number,
                        "x0": round(line.x0, 2),
                        "x1": round(line.x1, 2),
                        "y0": round(line.y0, 2),
                        "y1": round(line.y1, 2),
                        "line_width": round(line.x1 - line.x0, 2),
                        "font_size": round(line.max_font_size, 2),
                        "avg_font_size": round(line.avg_font_size, 2),
                        "bold": line.is_bold,
                    }
                )

                blocks.append(
                    ParsedBlock(
                        document_id=record.document_id,
                        page_number=line.page_number,
                        block_type=block_type,
                        text=cleaned_line,
                        heading_level=heading_level,
                        source_path=record.source_path,
                        parser_name=self.parser_name,
                        parser_version=self.parser_version,
                        metadata=metadata,
                    )
                )

        # Order cannot swap here. Later repair needs text from earlier repair.
        blocks = self.repair_heading_fragments(blocks)
        blocks = self.rebuild_flow_blocks(blocks)
        blocks = self.split_embedded_section_titles(blocks)
        blocks = self.repair_wrapped_numbered_section_titles(blocks)
        blocks = self.promote_margin_numbered_sections(blocks)
        blocks = self.split_inline_section_titles(blocks)

        return CanonicalDocument(
            document_id=record.document_id,
            document_type=record.document_type,
            source_path=record.source_path,
            file_name=record.file_name,
            version=record.version,
            blocks=blocks,
            metadata={
                "parser_name": self.parser_name,
                "parser_version": self.parser_version,
                "block_count": len(blocks),
                "structure_detection": "line_font_paragraph_table_heuristics",
            },
        )

    def extract_lines(self, document: fitz.Document) -> list[PDFLine]:
        fragments: list[PDFLine] = []

        for page_index, page in enumerate(document, start=1):
            page_dict = page.get_text("dict")
            page_height = float(page.rect.height)
            line_number = 0
            table_lines, replaced_regions = self.extract_vector_table_lines(
                page, page_index, page_height, line_number
            )

            for block in page_dict.get("blocks", []):
                for raw_line in block.get("lines", []):
                    spans = raw_line.get("spans", [])
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue

                    line_number += 1
                    sizes = [float(span.get("size", 0)) for span in spans if span.get("text", "").strip()]
                    fonts = [str(span.get("font", "")).lower() for span in spans]
                    bbox = raw_line.get("bbox", [0, 0, 0, 0])
                    if self.is_inside_replaced_table_region(bbox, replaced_regions):
                        continue

                    fragments.append(
                        PDFLine(
                            text=text,
                            page_number=page_index,
                            line_number=line_number,
                            x0=float(bbox[0]),
                            x1=float(bbox[2]),
                            y0=float(bbox[1]),
                            y1=float(bbox[3]),
                            page_height=page_height,
                            max_font_size=max(sizes) if sizes else 0,
                            avg_font_size=sum(sizes) / len(sizes) if sizes else 0,
                            is_bold=any(self.font_name_is_bold(font) for font in fonts),
                        )
                    )

            # Weak grid is skipped. Normal coordinate reader handles this area.
            for table_line in table_lines:
                line_number += 1
                table_line.line_number = line_number
                fragments.append(table_line)

        return self.rebuild_layout_lines(fragments)

    def extract_vector_table_lines(
        self,
        page: fitz.Page,
        page_number: int,
        page_height: float,
        line_number: int,
    ) -> tuple[list[PDFLine], list[tuple[float, float, float, float]]]:
        """Read a drawn table grid when its rows and columns are clear."""
        # find_tables may return the big outer frame also. We only want inner grid.
        try:
            tables = page.find_tables(strategy="lines_strict").tables
        except (RuntimeError, ValueError):
            return [], []

        extracted: list[PDFLine] = []
        replaced_regions: list[tuple[float, float, float, float]] = []
        for table in tables:
            rows = table.extract()
            start = self.vector_grid_start(rows)
            if start is None:
                continue

            grid_rows = rows[start:]
            row_boxes = table.rows[start:]
            populated = [self.nonempty_table_cells(row) for row in grid_rows]
            if not self.has_sufficient_grid_rows(grid_rows, populated):
                continue
            if not self.has_reliable_grid_content(grid_rows):
                continue

            cells = [cell for row in row_boxes for cell in row.cells if cell is not None]
            if not cells:
                continue
            x0 = min(cell[0] for cell in cells)
            x1 = max(cell[2] for cell in cells)
            y0 = min(row.bbox[1] for row in row_boxes)
            y1 = max(row.bbox[3] for row in row_boxes)
            replaced_regions.append((x0, y0, x1, y1))

            leading_template_columns = self.leading_empty_columns(grid_rows[0], grid_rows)
            is_symbol_matrix = self.is_symbol_matrix_header(grid_rows)
            for row_index, (row, row_box) in enumerate(zip(grid_rows, row_boxes)):
                cells = [
                    (
                        self.normalize_symbol_matrix_header_cell(cell)
                        if is_symbol_matrix and row_index == 0
                        else self.normalize_table_cell(cell)
                    )
                    for cell in row
                ]
                cells = cells[leading_template_columns:]
                while cells and not cells[-1]:
                    cells.pop()
                if not cells:
                    continue
                extracted.append(
                    PDFLine(
                        text=" | ".join(cells),
                        page_number=page_number,
                        line_number=line_number,
                        x0=float(row_box.bbox[0]),
                        x1=float(row_box.bbox[2]),
                        y0=float(row_box.bbox[1]),
                        y1=float(row_box.bbox[3]),
                        page_height=page_height,
                        max_font_size=0.0,
                        avg_font_size=0.0,
                        is_bold=False,
                        is_table_grid=True,
                    )
                )
        return extracted, replaced_regions

    def vector_grid_start(self, rows: list[list[str | None]]) -> int | None:
        """Return the first row of an inner 3+ column grid, if present."""
        # Continued table can have one dense row at end. Start from real first row.
        if self.is_sparse_matrix(rows):
            return 0
        for index, row in enumerate(rows):
            if self.nonempty_table_cells(row) >= 3:
                return index
        return None

    def nonempty_table_cells(self, row: list[str | None]) -> int:
        return sum(bool(self.normalize_table_cell(cell)) for cell in row)

    def leading_empty_columns(self, row: list[str | None], rows: list[list[str | None]]) -> int:
        count = 0
        for index, cell in enumerate(row):
            if self.normalize_table_cell(cell):
                break
            if any(
                index < len(candidate) and self.normalize_table_cell(candidate[index])
                for candidate in rows[1:]
            ):
                break
            count += 1
        return count

    def has_sufficient_grid_rows(self, rows: list[list[str | None]], populated: list[int]) -> bool:
        if len(rows) >= 3 and sum(count >= 2 for count in populated) >= 3:
            return True
        if (
            len(rows) >= 2
            and max((len(row) for row in rows), default=0) >= 4
            and max(populated, default=0) >= 4
            and sum(count >= 2 for count in populated) >= 2
        ):
            return True
        if self.is_symbol_matrix_header(rows):
            return True
        # One row is enough when table already has a clear 3-column header.
        return len(rows) == 2 and populated[0] >= 3 and populated[1] >= 2

    def is_symbol_matrix_header(self, rows: list[list[str | None]]) -> bool:
        """Recognize a sparse header page for a later eligibility matrix.

        The ruled grid supplies exact column boundaries.  Its first page often
        contains only the ``Type`` header and a category label such as
        ``Postpaid``; accepting that narrow shape lets later symbol rows retain
        their real column identities without inferring any values.
        """
        if len(rows) != 2:
            return False
        header = [self.normalize_table_cell(cell) for cell in rows[0]]
        label = [self.normalize_table_cell(cell) for cell in rows[1]]
        return (
            len(header) >= 5
            and header[0].casefold() == "type"
            and sum(bool(cell) for cell in header) >= 5
            and sum(bool(cell) for cell in label) == 1
        )

    def has_reliable_grid_content(self, rows: list[list[str | None]]) -> bool:
        """Accept repeated values or a stable sparse feature-matrix layout."""
        value_rows = 0
        for row in rows:
            text = " ".join(self.normalize_table_cell(cell) for cell in row)
            if re.search(r"\bRM\s*\d|\b\d+(?:\.\d+)?\s*(?:GB|MB|Mbps|hours?)\b", text, re.IGNORECASE):
                value_rows += 1
        return (
            value_rows >= 2
            or self.is_sparse_matrix(rows)
            or self.has_explicit_wide_header(rows)
            or self.has_dense_wide_row(rows)
            or self.is_symbol_matrix_header(rows)
        )

    def has_explicit_wide_header(self, rows: list[list[str | None]]) -> bool:
        if len(rows) != 2 or self.nonempty_table_cells(rows[0]) < 3:
            return False
        header_cells = [self.normalize_table_cell(cell) for cell in rows[0] if self.normalize_table_cell(cell)]
        return all(len(cell.split()) <= 5 for cell in header_cells)

    def has_dense_wide_row(self, rows: list[list[str | None]]) -> bool:
        """Accept a ruled plan matrix even when it contains no price values."""
        if len(rows) < 2 or max((len(row) for row in rows), default=0) < 4:
            return False
        populated = [self.nonempty_table_cells(row) for row in rows]
        return max(populated, default=0) >= 4 and sum(count >= 2 for count in populated) >= 2

    def is_sparse_matrix(self, rows: list[list[str | None]]) -> bool:
        """Recognize a wide grid where blank cells are part of the layout."""
        if len(rows) < 3 or max((len(row) for row in rows), default=0) < 3:
            return False
        patterns: dict[tuple[int, ...], int] = {}
        for row in rows:
            positions = tuple(
                index for index, cell in enumerate(row) if self.normalize_table_cell(cell)
            )
            if len(positions) >= 2:
                patterns[positions] = patterns.get(positions, 0) + 1
        return bool(patterns and max(patterns.values()) >= 3)

    def normalize_table_cell(self, value: str | None) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in (value or "").splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return ""

        text = lines[0]
        for line in lines[1:]:
            if text.endswith("-"):
                text = self.join_vertical_text(text, line)
            elif self.should_join_wrapped_cell_fragment(text, line):
                # Small lower-case line may be broken word, like "Unlimite" + "d".
                text += line
            else:
                text += f" {line}"
        return text.strip()

    def normalize_symbol_matrix_header_cell(self, value: str | None) -> str:
        """Keep complete wrapped header words distinct in a verified matrix."""
        return " ".join(
            line for line in (re.sub(r"\s+", " ", line).strip() for line in (value or "").splitlines()) if line
        )

    def should_join_wrapped_cell_fragment(self, previous: str, current: str) -> bool:
        if not re.search(r"[A-Za-z0-9]$", previous):
            return False
        tokens = re.findall(r"[A-Za-z0-9]+", previous)
        if not tokens or len(tokens[-1]) < 4:
            return False
        if re.match(r"^[A-Z]{1,3}(?=\s|[)\],.;:]|$)", current):
            return any(char.isupper() for char in tokens[-1])
        if re.match(r"^\d{1,2}(?=\s|[)\],.;:]|$)", current) and re.search(r"\d$", previous):
            return True
        fragment = re.match(r"^([a-z]{1,5})(?=\s|[)\],.;:]|$)", current)
        if fragment:
            return fragment.group(1) not in self.common_short_words
        # Product name may split like "Celco" and "mDigi" in two cells.
        return bool(re.match(r"^[a-z][A-Z][A-Za-z]*", current))

    def is_inside_replaced_table_region(
        self,
        bbox: list[float],
        regions: list[tuple[float, float, float, float]],
    ) -> bool:
        x0, y0, x1, y1 = (float(value) for value in bbox)
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        for left, top, right, bottom in regions:
            if left - 1 <= center_x <= right + 1 and top - 1 <= center_y <= bottom + 1:
                return True
            # Outer label is beside inner grid. Keeping it moves grid columns wrong.
            is_short_side_label = x1 <= left + 1 and x1 - x0 <= 120
            if is_short_side_label and top <= center_y <= bottom:
                return True
        return False

    def rebuild_layout_lines(self, lines: list[PDFLine]) -> list[PDFLine]:
        """Recover more human-readable reading order from PDF layout fragments."""

        if not lines:
            return []

        fragments = sorted(lines, key=lambda line: (line.page_number, line.y0, line.x0))
        stitched = self.stitch_vertical_fragments(fragments)
        row_merged = self.merge_same_row_fragments(stitched)
        row_merged = self.merge_parallel_header_rows(row_merged)
        rebuilt: list[PDFLine] = []
        for index, line in enumerate(row_merged, start=1):
            rebuilt.append(
                PDFLine(
                    text=line.text,
                    page_number=line.page_number,
                    line_number=index,
                    x0=line.x0,
                    x1=line.x1,
                    y0=line.y0,
                    y1=line.y1,
                    page_height=line.page_height,
                    max_font_size=line.max_font_size,
                    avg_font_size=line.avg_font_size,
                    is_bold=line.is_bold,
                    is_table_grid=line.is_table_grid,
                )
            )
        return rebuilt

    def merge_parallel_header_rows(self, rows: list[PDFLine]) -> list[PDFLine]:
        """Recover short wrapped headers while leaving data rows untouched."""
        merged: list[PDFLine] = []
        for row in rows:
            if merged and self.can_merge_parallel_header_rows(merged[-1], row):
                merged[-1] = self.merge_parallel_rows(merged[-1], row)
            else:
                merged.append(row)
        return merged

    def can_merge_parallel_header_rows(self, previous: PDFLine, current: PDFLine) -> bool:
        if previous.page_number != current.page_number or current.y0 - previous.y1 > 12:
            return False
        previous_cells = [cell.strip() for cell in previous.text.split("|")]
        current_cells = [cell.strip() for cell in current.text.split("|")]
        if len(previous_cells) < 3 or len(previous_cells) != len(current_cells):
            return False
        cells = [*previous_cells, *current_cells]
        if any(re.search(r"\d|RM|[✅✖️🔵]", cell, re.IGNORECASE) for cell in cells):
            return False
        return all(0 < len(cell.split()) <= 2 for cell in cells)

    def merge_parallel_rows(self, previous: PDFLine, current: PDFLine) -> PDFLine:
        cells = [
            self.join_vertical_text(left.strip(), right.strip())
            for left, right in zip(previous.text.split("|"), current.text.split("|"))
        ]
        return PDFLine(
            text=" | ".join(cells), page_number=previous.page_number, line_number=previous.line_number,
            x0=min(previous.x0, current.x0), x1=max(previous.x1, current.x1),
            y0=previous.y0, y1=current.y1, page_height=previous.page_height,
            max_font_size=max(previous.max_font_size, current.max_font_size),
            avg_font_size=(previous.avg_font_size + current.avg_font_size) / 2,
            is_bold=previous.is_bold or current.is_bold,
        )

    def stitch_vertical_fragments(self, fragments: list[PDFLine]) -> list[PDFLine]:
        """Join wrapped cells by column before restoring table row order."""
        stitched: list[PDFLine] = []
        ordered = sorted(fragments, key=lambda line: (line.page_number, round(line.x0 / 4), line.y0, line.x0))

        for fragment in ordered:
            if (
                stitched
                and self.can_stitch_vertical(stitched[-1], fragment)
                and (
                    not self.starts_parallel_table_row(fragment, ordered)
                    or self.is_obvious_continuation(stitched[-1], fragment)
                )
            ):
                stitched[-1] = self.merge_vertical_pair(stitched[-1], fragment)
                continue
            stitched.append(fragment)

        return sorted(stitched, key=lambda line: (line.page_number, line.y0, line.x0))

    def starts_parallel_table_row(self, candidate: PDFLine, lines: list[PDFLine]) -> bool:
        """A new line in multiple columns is a row, not a wrapped cell value."""
        return any(
            line is not candidate
            and line.page_number == candidate.page_number
            and abs(line.y0 - candidate.y0) <= 4.5
            and abs(line.x0 - candidate.x0) > 4
            for line in lines
        )

    def is_obvious_continuation(self, previous: PDFLine, current: PDFLine) -> bool:
        previous_text = previous.text.strip()
        current_text = current.text.strip()
        return (
            previous_text.endswith("-")
            or current_text.startswith("(")
            or (
                previous_text.isalpha()
                and len(previous_text) >= 4
                and current_text.isalpha()
                and current_text.islower()
                and len(current_text) <= 2
            )
        )

    def can_stitch_vertical(self, previous: PDFLine, current: PDFLine) -> bool:
        if previous.page_number != current.page_number:
            return False
        if current.y0 - previous.y1 > 10:
            return False
        if previous.x1 - previous.x0 > 190 or current.x1 - current.x0 > 190:
            return False
        if not self.horizontal_overlap(previous, current):
            return False
        if self.looks_like_atomic_value(previous.text) and self.looks_like_atomic_value(current.text):
            return False
        if previous.text.endswith("-") or current.text.startswith("("):
            return True
        if current.text[:1].islower():
            return True
        return not self.looks_like_atomic_value(previous.text) and not self.looks_like_atomic_value(current.text)

    def looks_like_atomic_value(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if len(stripped.split()) > 3:
            return False
        if re.fullmatch(r"\(?\d+(?:[./-]\d+)?(?:am|pm)?\)?", stripped, re.IGNORECASE):
            return True
        if re.fullmatch(r"RM\s*\d+(?:[./]\d+)?", stripped, re.IGNORECASE):
            return True
        if re.fullmatch(r"\d+\s*(?:GB|MB|TB|Days?|Day|Hours?|Hour|Mbps|mins?)", stripped, re.IGNORECASE):
            return True
        if re.fullmatch(r"Unlimited(?:\s+\d+\w+)?", stripped, re.IGNORECASE):
            return True
        return False

    def horizontal_overlap(self, left: PDFLine, right: PDFLine) -> bool:
        overlap = min(left.x1, right.x1) - max(left.x0, right.x0)
        min_width = min(left.x1 - left.x0, right.x1 - right.x0)
        if min_width < 12:
            return overlap > 0
        return overlap >= max(12.0, min_width * 0.35)

    def merge_vertical_pair(self, previous: PDFLine, current: PDFLine) -> PDFLine:
        text = self.join_vertical_text(previous.text, current.text)
        return PDFLine(
            text=text,
            page_number=previous.page_number,
            line_number=previous.line_number,
            x0=min(previous.x0, current.x0),
            x1=max(previous.x1, current.x1),
            y0=min(previous.y0, current.y0),
            y1=max(previous.y1, current.y1),
            page_height=previous.page_height,
            max_font_size=max(previous.max_font_size, current.max_font_size),
            avg_font_size=(previous.avg_font_size + current.avg_font_size) / 2,
            is_bold=previous.is_bold or current.is_bold,
        )

    def join_vertical_text(self, previous: str, current: str) -> str:
        if previous.endswith("-"):
            if previous[-2:-1].isdigit() and current[:1].isdigit():
                return f"{previous}{current}"
            if current[:1].isupper():
                return f"{previous}{current}"
            return f"{previous[:-1]}{current}"
        if previous.isalpha() and len(previous) >= 4 and current.isalpha() and current.islower() and len(current) <= 2:
            return f"{previous}{current}"
        return f"{previous} {current}".strip()

    def merge_same_row_fragments(self, fragments: list[PDFLine]) -> list[PDFLine]:
        merged: list[PDFLine] = []
        current_row: list[PDFLine] = []

        for fragment in fragments:
            if current_row and not self.belongs_to_same_row(current_row, fragment):
                merged.append(self.merge_row(current_row))
                current_row = []
            current_row.append(fragment)

        if current_row:
            merged.append(self.merge_row(current_row))

        return merged

    def belongs_to_same_row(self, row: list[PDFLine], candidate: PDFLine) -> bool:
        previous = row[-1]
        if previous.page_number != candidate.page_number:
            return False
        row_center = sum((item.y0 + item.y1) / 2 for item in row) / len(row)
        candidate_center = (candidate.y0 + candidate.y1) / 2
        row_top = min(item.y0 for item in row)
        # Wrapped cell becomes taller. Compare row top, not only row centre.
        return abs(row_center - candidate_center) <= 2.5 or abs(candidate.y0 - row_top) <= 4.5

    def merge_row(self, row: list[PDFLine]) -> PDFLine:
        if len(row) == 1:
            return row[0]

        ordered = sorted(row, key=lambda item: item.x0)
        parts = [item.text.strip() for item in ordered if item.text.strip()]
        text = " | ".join(parts)

        return PDFLine(
            text=text,
            page_number=ordered[0].page_number,
            line_number=ordered[0].line_number,
            x0=min(item.x0 for item in ordered),
            x1=max(item.x1 for item in ordered),
            y0=min(item.y0 for item in ordered),
            y1=max(item.y1 for item in ordered),
            page_height=ordered[0].page_height,
            max_font_size=max(item.max_font_size for item in ordered),
            avg_font_size=sum(item.avg_font_size for item in ordered) / len(ordered),
            is_bold=any(item.is_bold for item in ordered),
        )

    def font_name_is_bold(self, font_name: str) -> bool:
        return any(token in font_name for token in ("bold", "black", "semibold", "demi"))

    def estimate_body_font_size(self, lines: list[PDFLine]) -> float:
        sizes = [line.avg_font_size for line in lines if line.avg_font_size > 0 and len(line.text) > 20]
        return float(median(sizes)) if sizes else 0.0

    def find_repeated_margin_lines(self, lines: list[PDFLine], min_pages: int = 3) -> set[str]:
        pages_by_text: dict[str, set[int]] = {}

        for line in lines:
            if not self.is_margin_line(line):
                continue
            normalized = self.normalize_for_margin_check(line.text)
            if not normalized or len(normalized) > 160:
                continue
            pages_by_text.setdefault(normalized, set()).add(line.page_number)

        return {text for text, pages in pages_by_text.items() if len(pages) >= min_pages}

    def is_margin_line(self, line: PDFLine) -> bool:
        top_band = line.y1 <= line.page_height * 0.12
        bottom_band = line.y0 >= line.page_height * 0.88
        return top_band or bottom_band

    def normalize_for_margin_check(self, text: str) -> str:
        text = re.sub(r"\b\d+\b", "#", text.lower())
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def clean_heading_text(self, text: str) -> str:
        return re.sub(r"^[-•\uf0b7]\s+", "", text).strip()

    def rebuild_flow_blocks(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        rebuilt: list[ParsedBlock] = []
        index = 0

        while index < len(blocks):
            block = blocks[index]
            if block.metadata.get("repeated_margin_noise"):
                index += 1
                continue
            if block.block_type == BlockType.TABLE:
                grouped, index = self.collect_same_type(blocks, index, BlockType.TABLE)
                rebuilt.append(self.merge_blocks(grouped, separator="\n", merge_kind="table_rows"))
                continue

            if block.block_type == BlockType.TEXT:
                grouped, index = self.collect_paragraph_blocks(blocks, index)
                rebuilt.append(self.merge_blocks(grouped, separator=" ", merge_kind="paragraph_lines"))
                continue

            if block.block_type == BlockType.LIST_ITEM:
                grouped, index = self.collect_list_item_blocks(blocks, index)
                rebuilt.append(self.merge_blocks(grouped, separator=" ", merge_kind="list_item_lines"))
                continue

            rebuilt.append(block)
            index += 1

        return rebuilt

    def split_embedded_section_titles(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        """Promote a standalone numbered title embedded in an outer layout table."""
        # One table block can become text, heading, then text again.
        rebuilt: list[ParsedBlock] = []
        for block in blocks:
            if block.block_type != BlockType.TABLE:
                rebuilt.append(block)
                continue

            pending: list[str] = []
            for raw_line in block.text.splitlines():
                title = raw_line.strip()
                if self.looks_like_embedded_section_title(title):
                    if pending:
                        rebuilt.append(block.model_copy(update={"text": "\n".join(pending)}))
                        pending = []
                    depth = title.split(maxsplit=1)[0].rstrip(".").count(".") + 1
                    rebuilt.append(
                        block.model_copy(
                            update={
                                "text": title,
                                "block_type": BlockType.HEADING,
                                "heading_level": min(depth, 4),
                                "metadata": {**block.metadata, "structure_hint": "embedded_table_section_title"},
                            }
                        )
                    )
                else:
                    pending.append(raw_line)
            if pending:
                rebuilt.append(block.model_copy(update={"text": "\n".join(pending)}))
        return rebuilt

    def split_inline_section_titles(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        """Separate a left-side field label from a numbered section on its row.

        Some PDF layout tables place a short label in the left cell and a
        bold numbered section title in the right cell.  Coordinate rebuilding
        can combine them into one heading (for example, ``Visuals 3. FAQs``).
        Split only that high-confidence, whole-line pattern.
        """
        rebuilt: list[ParsedBlock] = []
        pattern = re.compile(
            r"^(?P<label>[A-Za-z][A-Za-z &/\-]{0,40}?)\s+(?P<title>\d+\.\s+[A-Z][A-Za-z0-9(),/&\- ]{2,})$"
        )
        for block in blocks:
            match = pattern.match(block.text.strip())
            if (
                block.block_type == BlockType.HEADING
                and block.heading_level != 1
                and bool(block.metadata.get("bold"))
                and match
            ):
                label = match.group("label").strip()
                title = match.group("title").strip()
                depth = title.split(maxsplit=1)[0].rstrip(".").count(".") + 1
                rebuilt.append(block.model_copy(update={"text": label}))
                rebuilt.append(
                    block.model_copy(
                        update={
                            "text": title,
                            "block_type": BlockType.HEADING,
                            "heading_level": min(depth, 4),
                            "metadata": {**block.metadata, "structure_hint": "inline_section_title"},
                        }
                    )
                )
            else:
                rebuilt.append(block)
        return rebuilt

    def promote_margin_numbered_sections(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        """Recover a bold, left-aligned section lost as a list item in layout rebuild."""
        rebuilt: list[ParsedBlock] = []
        for block in blocks:
            x0 = float(block.metadata.get("x0", float("inf")))
            is_margin_section = (
                block.block_type == BlockType.LIST_ITEM
                and bool(block.metadata.get("bold"))
                and x0 <= 110
                and self.looks_like_embedded_section_title(block.text)
            )
            if is_margin_section:
                depth = block.text.split(maxsplit=1)[0].rstrip(".").count(".") + 1
                rebuilt.append(
                    block.model_copy(
                        update={
                            "block_type": BlockType.HEADING,
                            "heading_level": min(depth, 4),
                            "metadata": {**block.metadata, "structure_hint": "margin_numbered_section"},
                        }
                    )
                )
            else:
                rebuilt.append(block)
        return rebuilt

    def repair_wrapped_numbered_section_titles(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        """Join a numbered title when its closing bracket is in next block."""
        rebuilt: list[ParsedBlock] = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            x0 = float(block.metadata.get("x0", float("inf")))
            is_wrapped_title = (
                block.block_type == BlockType.LIST_ITEM
                and bool(block.metadata.get("bold"))
                and x0 <= 110
                and block.text.count("(") > block.text.count(")")
                and following is not None
                and following.block_type == BlockType.TABLE
            )
            if not is_wrapped_title:
                rebuilt.append(block)
                index += 1
                continue

            # Closing bracket must be near start and before any real table row.
            close_index = following.text.find(")")
            if close_index < 0 or close_index > 80 or "|" in following.text[:close_index]:
                rebuilt.append(block)
                index += 1
                continue

            title = f"{block.text} {following.text[:close_index + 1]}".strip()
            if not self.looks_like_embedded_section_title(title):
                rebuilt.append(block)
                index += 1
                continue

            depth = title.split(maxsplit=1)[0].rstrip(".").count(".") + 1
            rebuilt.append(
                block.model_copy(
                    update={
                        "text": title,
                        "block_type": BlockType.HEADING,
                        "heading_level": min(depth, 4),
                        "metadata": {**block.metadata, "structure_hint": "wrapped_section_title"},
                    }
                )
            )
            remaining = following.text[close_index + 1:].lstrip()
            if remaining:
                rebuilt.append(following.model_copy(update={"text": remaining}))
            index += 2
        return rebuilt

    def collect_same_type(
        self,
        blocks: list[ParsedBlock],
        start: int,
        block_type: BlockType,
    ) -> tuple[list[ParsedBlock], int]:
        page = blocks[start].page_number
        grouped: list[ParsedBlock] = []
        index = start

        while index < len(blocks):
            candidate = blocks[index]
            if candidate.page_number != page or candidate.block_type != block_type:
                break
            grouped.append(candidate)
            index += 1

        return grouped, index

    def repair_heading_fragments(self, blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        repaired: list[ParsedBlock] = []
        for index, block in enumerate(blocks):
            if not self.is_fragmented_heading_candidate(block):
                repaired.append(block)
                continue

            next_block = blocks[index + 1] if index + 1 < len(blocks) else None
            if next_block is None or next_block.block_type != BlockType.TEXT:
                repaired.append(block)
                continue
            if not next_block.text.isalpha() or not next_block.text[:1].islower() or len(next_block.text) > 6:
                repaired.append(block)
                continue

            repaired.append(block.model_copy(update={"block_type": BlockType.TEXT, "heading_level": None}))
        return repaired

    def is_fragmented_heading_candidate(self, block: ParsedBlock) -> bool:
        return (
            block.block_type == BlockType.HEADING
            and block.heading_level is not None
            and block.heading_level > 1
            and " " not in block.text
            and block.text.isalpha()
            and 4 <= len(block.text) <= 12
        )

    def collect_paragraph_blocks(self, blocks: list[ParsedBlock], start: int) -> tuple[list[ParsedBlock], int]:
        page = blocks[start].page_number
        grouped: list[ParsedBlock] = []
        index = start

        while index < len(blocks):
            candidate = blocks[index]
            if candidate.page_number != page or candidate.block_type != BlockType.TEXT:
                break
            if candidate.metadata.get("repeated_margin_noise"):
                break
            if grouped and not self.is_same_paragraph_flow(grouped[-1], candidate):
                break
            grouped.append(candidate)
            index += 1

        return grouped, index

    def is_same_paragraph_flow(self, previous: ParsedBlock, candidate: ParsedBlock) -> bool:
        """Avoid joining separate PDF columns or visually separated paragraphs."""
        previous_y1 = float(previous.metadata.get("y1", 0))
        candidate_y0 = float(candidate.metadata.get("y0", previous_y1))
        if candidate_y0 - previous_y1 > 22:
            return False
        previous_x0 = float(previous.metadata.get("x0", 0))
        candidate_x0 = float(candidate.metadata.get("x0", previous_x0))
        return abs(candidate_x0 - previous_x0) <= 36

    def collect_list_item_blocks(self, blocks: list[ParsedBlock], start: int) -> tuple[list[ParsedBlock], int]:
        page = blocks[start].page_number
        grouped = [blocks[start]]
        index = start + 1

        while index < len(blocks):
            candidate = blocks[index]
            if candidate.page_number != page or candidate.block_type != BlockType.TEXT:
                break
            if not self.is_list_item_continuation(grouped[-1], candidate):
                break
            grouped.append(candidate)
            index += 1

        return grouped, index

    def is_list_item_continuation(self, previous: ParsedBlock, candidate: ParsedBlock) -> bool:
        """Attach an indented wrapped line to its numbered or lettered item."""
        previous_y1 = float(previous.metadata.get("y1", 0))
        candidate_y0 = float(candidate.metadata.get("y0", previous_y1))
        if candidate_y0 - previous_y1 > 24:
            return False
        previous_x0 = float(previous.metadata.get("x0", 0))
        candidate_x0 = float(candidate.metadata.get("x0", previous_x0))
        return candidate.text[:1].islower() or candidate_x0 >= previous_x0 + 10

    def merge_blocks(self, blocks: list[ParsedBlock], separator: str, merge_kind: str) -> ParsedBlock:
        if len(blocks) == 1:
            return blocks[0]

        first = blocks[0]
        text_parts = [block.text.strip() for block in blocks if block.text.strip()]
        text = self.join_text_parts(text_parts, separator)
        if separator == " ":
            text = self.normalize_paragraph_spacing(text)

        metadata = dict(first.metadata)
        metadata.update(
            {
                "merged_block_count": len(blocks),
                "merge_kind": merge_kind,
                "source_line_numbers": [block.metadata.get("line_number") for block in blocks],
            }
        )

        return first.model_copy(update={"text": text, "metadata": metadata})

    def join_text_parts(self, parts: list[str], separator: str) -> str:
        if not parts:
            return ""
        text = parts[0]
        previous = parts[0]
        for part in parts[1:]:
            if separator == " " and self.should_join_without_space(previous, part):
                text += part
            else:
                text += separator + part
            previous = part
        return text

    def should_join_without_space(self, previous: str, current: str) -> bool:
        return (
            " " not in previous
            and " " not in current
            and previous[:1].isalpha()
            and previous[-1:].isalpha()
            and current[:1].islower()
            and current.isalpha()
            and len(current) <= 6
        )

    def normalize_paragraph_spacing(self, text: str) -> str:
        text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
