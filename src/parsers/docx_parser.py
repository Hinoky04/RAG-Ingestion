from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from src.parsers.base_parser import BaseParser
from src.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


class DOCXParser(BaseParser):
    """Basic DOCX parser using python-docx."""

    parser_name = "python-docx"
    parser_version = "v1.0"

    numbered_heading_pattern = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S+")

    def block_type_for_paragraph(self, text: str, style_name: str) -> tuple[BlockType, int | None, dict[str, object]]:
        metadata: dict[str, object] = {"docx_style": style_name}
        style = style_name.lower()

        if style.startswith("heading"):
            level = self.heading_level(style)
            metadata["structure_hint"] = "docx_heading_style"
            return BlockType.HEADING, level, metadata

        if self.numbered_heading_pattern.match(text) and len(text) <= 120:
            metadata["structure_hint"] = "numbered_heading"
            return BlockType.HEADING, 2, metadata

        if style.startswith("list"):
            return BlockType.LIST_ITEM, None, metadata

        return BlockType.TEXT, None, metadata

    def heading_level(self, style_name: str) -> int:
        match = re.search(r"heading\s+(\d+)", style_name)
        if not match:
            return 2
        return min(int(match.group(1)), 4)

    def table_text(self, table) -> str:
        rows: list[str] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        return "\n".join(rows).strip()

    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        source_path = Path(record.source_path)
        doc = Document(source_path)
        blocks: list[ParsedBlock] = []

        for index, paragraph in enumerate(doc.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue

            style_name = paragraph.style.name if paragraph.style is not None else "unknown"
            block_type, heading_level, metadata = self.block_type_for_paragraph(text, style_name)
            metadata.update(
                {
                    "source_format": "docx",
                    "paragraph_index": index,
                }
            )

            blocks.append(
                ParsedBlock(
                    document_id=record.document_id,
                    page_number=None,
                    block_type=block_type,
                    text=text,
                    heading_level=heading_level,
                    source_path=record.source_path,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    metadata=metadata,
                )
            )

        for index, table in enumerate(doc.tables, start=1):
            text = self.table_text(table)
            if not text:
                continue

            blocks.append(
                ParsedBlock(
                    document_id=record.document_id,
                    page_number=None,
                    block_type=BlockType.TABLE,
                    text=text,
                    heading_level=None,
                    source_path=record.source_path,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    metadata={
                        "source_format": "docx",
                        "table_index": index,
                        "possible_table": True,
                    },
                )
            )

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
                "structure_detection": "docx_styles_and_basic_tables",
            },
        )
