from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import fitz

from src.parsers.base_parser import BaseParser
from src.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


@dataclass
class PDFLine:
    text: str
    page_number: int
    line_number: int
    y0: float
    y1: float
    page_height: float
    max_font_size: float
    avg_font_size: float
    is_bold: bool
    x0: float = 0.0
    x1: float = 0.0


class PDFParser(BaseParser):
    """Local PDF parser based on PyMuPDF."""

    parser_name = "pymupdf"
    parser_version = "v1.3"

    section_pattern = re.compile(r"^\d+\.(?:\d+\.)*\s+[A-Z][A-Za-z0-9(),/&\- ]{2,}$")
    step_pattern = re.compile(r"^Step\s+\d+\s*:", re.IGNORECASE)
    faq_pattern = re.compile(r"^Q\d*\.?\s+", re.IGNORECASE)

    def classify_line(self, line: PDFLine, body_font_size: float) -> tuple[BlockType, int | None, dict[str, object]]:
        metadata: dict[str, object] = {}
        stripped = line.text.strip()

        if self.looks_like_table_row(stripped):
            metadata["possible_table"] = True
            return BlockType.TABLE, None, metadata

        if self.looks_like_numeric_table_label(stripped):
            metadata["structure_hint"] = "numeric_table_label"
            return BlockType.TEXT, None, metadata

        if self.looks_like_numbered_sentence(stripped):
            metadata["structure_hint"] = "numbered_sentence"
            return BlockType.TEXT, None, metadata

        if self.step_pattern.match(stripped):
            metadata["structure_hint"] = "procedure_step"
            return BlockType.HEADING, 3, metadata

        if self.faq_pattern.match(stripped):
            metadata["structure_hint"] = "faq_question"
            return BlockType.HEADING, 3, metadata

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
        if not re.search(r"\b\d{3,}\b", line):
            return False
        words = [word for word in re.split(r"\W+", line) if word]
        return len(words) <= 4

    def looks_like_numeric_table_label(self, line: str) -> bool:
        return bool(re.match(r"^\d+\s+[A-Za-z][A-Za-z0-9/&()\-+ ]*$", line))

    def looks_like_numbered_sentence(self, line: str) -> bool:
        return bool(re.match(r"^\d+\.\s+\S+", line)) and len(line.split()) > 5

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
        if "\t" in line:
            return True
        if line.count("|") >= 2:
            return True

        # Many generated and public PDFs flatten table cells into spaced columns.
        spaced_columns = re.search(r"\S\s{2,}\S", line)
        has_multiple_numbers = len(re.findall(r"\b\d+[\d.,%]*\b", line)) >= 2
        return bool(spaced_columns and has_multiple_numbers)

    def looks_like_list_item(self, line: str) -> bool:
        return bool(re.match(r"^(?:[-•\uf0b7]|\d+\.)\s+\S+", line))

    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        source_path = Path(record.source_path)
        blocks: list[ParsedBlock] = []

        with fitz.open(source_path) as document:
            lines = self.extract_lines(document)
            body_font_size = self.estimate_body_font_size(lines)
            margin_noise = self.find_repeated_margin_lines(lines)

            for line in lines:
                cleaned_line = line.text.strip()
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

        blocks = self.repair_heading_fragments(blocks)
        blocks = self.rebuild_flow_blocks(blocks)

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

        return self.rebuild_layout_lines(fragments)

    def rebuild_layout_lines(self, lines: list[PDFLine]) -> list[PDFLine]:
        """Recover more human-readable reading order from PDF layout fragments."""

        if not lines:
            return []

        fragments = sorted(lines, key=lambda line: (line.page_number, line.y0, line.x0))
        stitched = self.stitch_vertical_fragments(fragments)
        row_merged = self.merge_same_row_fragments(stitched)
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
                )
            )
        return rebuilt

    def stitch_vertical_fragments(self, fragments: list[PDFLine]) -> list[PDFLine]:
        stitched: list[PDFLine] = []

        for fragment in fragments:
            if stitched and self.can_stitch_vertical(stitched[-1], fragment):
                stitched[-1] = self.merge_vertical_pair(stitched[-1], fragment)
                continue
            stitched.append(fragment)

        return stitched

    def can_stitch_vertical(self, previous: PDFLine, current: PDFLine) -> bool:
        if previous.page_number != current.page_number:
            return False
        if current.y0 - previous.y1 > 10:
            return False
        if abs(previous.x0 - current.x0) > 4:
            return False
        if previous.x1 - previous.x0 > 190 or current.x1 - current.x0 > 190:
            return False
        if max(len(previous.text.split()), len(current.text.split())) > 6:
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
            return f"{previous[:-1]}{current}"
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
        return abs(row_center - candidate_center) <= 4.5

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
            if self.is_sidebar_noise(block):
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

    def is_sidebar_noise(self, block: ParsedBlock) -> bool:
        x0 = float(block.metadata.get("x0", 999))
        line_width = float(block.metadata.get("line_width", 999))
        if x0 > 70 or line_width > 90:
            return False
        if block.block_type not in {BlockType.HEADING, BlockType.TEXT}:
            return False
        if self.section_pattern.match(block.text) or self.step_pattern.match(block.text) or self.faq_pattern.match(block.text):
            return False
        if len(block.text.split()) > 4:
            return False
        return True

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
            grouped.append(candidate)
            index += 1

        return grouped, index

    def collect_list_item_blocks(self, blocks: list[ParsedBlock], start: int) -> tuple[list[ParsedBlock], int]:
        page = blocks[start].page_number
        grouped = [blocks[start]]
        index = start + 1

        while index < len(blocks):
            candidate = blocks[index]
            if candidate.page_number != page or candidate.block_type != BlockType.TEXT:
                break
            if not candidate.text[:1].islower():
                break
            grouped.append(candidate)
            index += 1

        return grouped, index

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
