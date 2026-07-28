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


class PDFParser(BaseParser):
    """Local PDF parser based on PyMuPDF."""

    parser_name = "pymupdf"
    parser_version = "v1.3"

    section_pattern = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9(),/&\- ]{2,}$")
    step_pattern = re.compile(r"^Step\s+\d+\s*:", re.IGNORECASE)
    faq_pattern = re.compile(r"^Q\d*\.?\s+", re.IGNORECASE)

    def classify_line(self, line: PDFLine, body_font_size: float) -> tuple[BlockType, int | None, dict[str, object]]:
        metadata: dict[str, object] = {}
        stripped = line.text.strip()

        if self.looks_like_table_row(stripped):
            metadata["possible_table"] = True
            return BlockType.TABLE, None, metadata

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

        blocks = self.rebuild_flow_blocks(blocks)

        return CanonicalDocument(
            document_id=record.document_id,
            client_id=record.client_id,
            document_type=record.document_type,
            source_path=record.source_path,
            file_name=record.file_name,
            version=record.version,
            access_scope=record.access_scope,
            blocks=blocks,
            metadata={
                "parser_name": self.parser_name,
                "parser_version": self.parser_version,
                "block_count": len(blocks),
                "structure_detection": "line_font_paragraph_table_heuristics",
            },
        )

    def extract_lines(self, document: fitz.Document) -> list[PDFLine]:
        lines: list[PDFLine] = []

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

                    lines.append(
                        PDFLine(
                            text=text,
                            page_number=page_index,
                            line_number=line_number,
                            y0=float(bbox[1]),
                            y1=float(bbox[3]),
                            page_height=page_height,
                            max_font_size=max(sizes) if sizes else 0,
                            avg_font_size=sum(sizes) / len(sizes) if sizes else 0,
                            is_bold=any(self.font_name_is_bold(font) for font in fonts),
                        )
                    )

        return lines

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
                rebuilt.append(block)
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
        text = separator.join(text_parts)
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

    def normalize_paragraph_spacing(self, text: str) -> str:
        text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
