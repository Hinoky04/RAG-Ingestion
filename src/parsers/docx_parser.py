from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.parsers.base_parser import BaseParser
from src.representation.schemas import BlockType, CanonicalDocument, DocumentRecord, ParsedBlock


class DOCXParser(BaseParser):
    """Parse DOCX paragraphs and tables in their original document order."""

    parser_name = "python-docx"
    parser_version = "v1.5"

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

    def paragraph_text_and_links(self, paragraph: Paragraph, part) -> tuple[str, list[dict[str, str]]]:
        """Keep external hyperlink targets available to retrieval without following them."""

        text = paragraph.text.strip()
        links: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        for hyperlink in paragraph._p.xpath(".//w:hyperlink"):
            relationship_id = hyperlink.get(qn("r:id"))
            if not relationship_id:
                continue

            relationship = part.rels.get(relationship_id)
            if relationship is None or not relationship.is_external:
                continue

            url = relationship.target_ref.strip()
            if not url or url in seen_urls:
                continue

            label = "".join(hyperlink.xpath(".//w:t/text()")).strip() or url
            links.append({"text": label, "url": url})
            seen_urls.add(url)

        # Keep a URL with the sentence where its hyperlink label appeared.
        # A separate "Links:" line becomes an unrelated retrieval bullet and
        # obscures the fact that the URL qualifies the preceding statement.
        search_from = 0
        for link in links:
            url = link["url"]
            if url in text:
                continue
            label = link["text"]
            position = text.find(label, search_from) if label else -1
            if position >= 0:
                end = position + len(label)
                text = f"{text[:end]} ({url}){text[end:]}"
                search_from = end + len(url) + 3
            else:
                text = f"{text}\n{label}: {url}".strip()

        style_name = paragraph.style.name if paragraph.style is not None else ""
        if text and style_name.lower().startswith("list") and not text.startswith(("- ", "• ", "* ")):
            text = f"- {text}"

        return text, links

    def table_text(self, table: Table, part) -> tuple[str, list[dict[str, str]]]:
        rows: list[str] = []
        links: list[dict[str, str]] = []
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                cell_text, cell_links = self.cell_text(cell, part)
                links.extend(cell_links)
                if cell_text:
                    cells.append(cell_text)

            if not cells:
                continue
            if len(cells) == 2 and cells[0] == cells[1]:
                rows.append(cells[0])
            elif len(cells) == 2:
                value_lines = [line for line in cells[1].splitlines() if line.strip()]
                if len(value_lines) > 1 and all(line.lstrip().startswith("-") for line in value_lines):
                    rows.append(f"{cells[0]}:\n{cells[1]}")
                else:
                    rows.append(f"{cells[0]}: {cells[1]}")
            else:
                rows.append(" | ".join(cells))

        return "\n".join(rows).strip(), links

    def direct_cell_text(self, cell, part) -> tuple[str, list[dict[str, str]]]:
        parts: list[str] = []
        links: list[dict[str, str]] = []
        for element in cell._tc.iterchildren():
            if not isinstance(element, CT_P):
                continue

            text, paragraph_links = self.paragraph_text_and_links(Paragraph(element, cell), part)
            if text:
                parts.append(text)
            links.extend(paragraph_links)

        return "\n".join(parts).strip(), links

    def cell_text(self, cell, part) -> tuple[str, list[dict[str, str]]]:
        """Read cell paragraphs and nested tables in their XML order."""

        parts: list[str] = []
        links: list[dict[str, str]] = []
        for element in cell._tc.iterchildren():
            if isinstance(element, CT_P):
                text, paragraph_links = self.paragraph_text_and_links(Paragraph(element, cell), part)
            elif isinstance(element, CT_Tbl):
                text, paragraph_links = self.table_text(Table(element, cell), part)
            else:
                continue

            if text:
                parts.append(text)
            links.extend(paragraph_links)

        return "\n".join(parts).strip(), links

    def table_structures(self, table: Table, part, depth: int = 0) -> list[dict[str, object]]:
        rows: list[list[str]] = []
        structures: list[dict[str, object]] = []

        for row in table.rows:
            row_cells: list[str] = []
            for cell in row.cells:
                text, _ = self.direct_cell_text(cell, part)
                row_cells.append(text)
            if any(cell.strip() for cell in row_cells):
                rows.append(row_cells)

        if rows:
            structures.append(
                {
                    "depth": depth,
                    "row_count": len(rows),
                    "col_count": max(len(row) for row in rows),
                    "rows": rows,
                }
            )

        for row in table.rows:
            for cell in row.cells:
                for nested in cell.tables:
                    structures.extend(self.table_structures(nested, part, depth + 1))

        return structures

    def table_anchor(self, table: Table, part) -> str:
        """Return a short visible label for a nested table without inferring scope."""

        labels: list[str] = []
        for row in table.rows[:2]:
            for cell in row.cells:
                text, _ = self.direct_cell_text(cell, part)
                label = " ".join(text.split())
                if label and label not in labels:
                    labels.append(label)
        return " | ".join(labels[:3])[:240] or "Table"

    def table_fragments(
        self,
        table: Table,
        part,
        table_path: str = "root",
        parent_table_path: str | None = None,
    ) -> list[dict[str, object]]:
        """Preserve paragraph/table order inside DOCX cells as additive metadata."""

        fragments: list[dict[str, object]] = []
        seen_cells: set[int] = set()
        for row_index, row in enumerate(table.rows, start=1):
            for cell_index, cell in enumerate(row.cells, start=1):
                cell_identity = id(cell._tc)
                if cell_identity in seen_cells:
                    continue
                seen_cells.add(cell_identity)

                cell_path = f"{table_path}.r{row_index}c{cell_index}"
                direct_fragments: list[dict[str, object]] = []
                nested_tables: list[tuple[dict[str, object], Table, str]] = []
                nested_index = 0
                for xml_ordinal, element in enumerate(cell._tc.iterchildren(), start=1):
                    if isinstance(element, CT_P):
                        paragraph = Paragraph(element, cell)
                        text, _ = self.paragraph_text_and_links(paragraph, part)
                        if not text:
                            continue
                        direct_fragments.append(
                            {
                                "kind": "paragraph",
                                "table_path": table_path,
                                "parent_table_path": parent_table_path,
                                "cell_path": cell_path,
                                "xml_ordinal": xml_ordinal,
                                "text": text,
                                "style": paragraph.style.name if paragraph.style is not None else "unknown",
                            }
                        )
                    elif isinstance(element, CT_Tbl):
                        nested_index += 1
                        nested_path = f"{cell_path}.table{nested_index}"
                        nested_table = Table(element, cell)
                        fragment = {
                            "kind": "nested_table",
                            "table_path": nested_path,
                            "parent_table_path": table_path,
                            "cell_path": cell_path,
                            "xml_ordinal": xml_ordinal,
                            "anchor": self.table_anchor(nested_table, part),
                        }
                        direct_fragments.append(fragment)
                        nested_tables.append((fragment, nested_table, nested_path))

                for index, fragment in enumerate(direct_fragments):
                    if fragment["kind"] != "paragraph":
                        continue
                    previous = next(
                        (item for item in reversed(direct_fragments[:index]) if item["kind"] == "nested_table"), None
                    )
                    following = next(
                        (item for item in direct_fragments[index + 1 :] if item["kind"] == "nested_table"), None
                    )
                    if previous is not None:
                        fragment["previous_table_anchor"] = previous["anchor"]
                    if following is not None:
                        fragment["next_table_anchor"] = following["anchor"]

                fragments.extend(direct_fragments)
                for _, nested_table, nested_path in nested_tables:
                    fragments.extend(self.table_fragments(nested_table, part, nested_path, table_path))

        return fragments

    def iter_body_items(self, doc: Document):
        """Yield paragraphs and tables in the order users see them in Word."""

        for element in doc.element.body.iterchildren():
            if isinstance(element, CT_P):
                yield Paragraph(element, doc)
            elif isinstance(element, CT_Tbl):
                yield Table(element, doc)

    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        source_path = Path(record.source_path)
        doc = Document(source_path)
        blocks: list[ParsedBlock] = []

        paragraph_index = 0
        table_index = 0
        for item in self.iter_body_items(doc):
            if isinstance(item, Paragraph):
                paragraph_index += 1
                text, links = self.paragraph_text_and_links(item, doc.part)
                if not text:
                    continue

                style_name = item.style.name if item.style is not None else "unknown"
                block_type, heading_level, metadata = self.block_type_for_paragraph(text, style_name)
                metadata.update({"source_format": "docx", "paragraph_index": paragraph_index})
                if links:
                    metadata["hyperlinks"] = links
            else:
                table_index += 1
                text, links = self.table_text(item, doc.part)
                if not text:
                    continue

                fragments = self.table_fragments(item, doc.part)

                block_type = BlockType.TABLE
                heading_level = None
                metadata = {
                    "source_format": "docx",
                    "table_index": table_index,
                    "possible_table": True,
                    "table_structures": self.table_structures(item, doc.part),
                    "table_fragments": fragments,
                }
                if links:
                    metadata["hyperlinks"] = links

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
                "structure_detection": "docx_ordered_blocks_tables_and_hyperlinks",
            },
        )
