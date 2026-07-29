from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from src.representation.schemas import BlockType, CanonicalDocument, DocumentChunk, ParsedBlock


MIN_HEADINGS_FOR_STRUCTURE = 3
MAX_WORDS = 350
OVERLAP_WORDS = 50
MIN_CHUNK_WORDS = 25
PRICE_ROW_PATTERN = re.compile(r"\bRM\s*\d", re.IGNORECASE)


@dataclass
class ChunkDraft:
    section_path: str
    blocks: list[ParsedBlock] = field(default_factory=list)


def word_count(text: str) -> int:
    return len(text.split())


def heading_count(document: CanonicalDocument) -> int:
    return sum(1 for block in document.blocks if block.block_type == BlockType.HEADING)


def group_by_heading(document: CanonicalDocument) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    current = ChunkDraft(section_path="Introduction")

    for block in document.blocks:
        if block.block_type == BlockType.HEADING:
            if current.blocks:
                drafts.append(current)
            current = ChunkDraft(section_path=block.text, blocks=[block])
            continue

        current.blocks.append(block)

    if current.blocks:
        drafts.append(current)

    return drafts


def group_web_by_major_heading(document: CanonicalDocument) -> list[ChunkDraft]:
    """Keep small web subheadings with their parent, but split major sections.

    Web help pages often mark every step as a heading. Treating every one as a
    new section makes the chunker merge unrelated short drafts later. For web
    pages, level 1-2 headings are a safer boundary; level 3+ headings stay as
    local structure inside the current section.
    """

    drafts: list[ChunkDraft] = []
    current = ChunkDraft(section_path="Introduction")

    for block in document.blocks:
        is_heading = block.block_type == BlockType.HEADING
        level = block.heading_level
        starts_major_section = is_heading and (level is None or level <= 2)

        if starts_major_section:
            if current.blocks:
                drafts.append(current)
            current = ChunkDraft(section_path=block.text, blocks=[block])
            continue

        current.blocks.append(block)

    if current.blocks:
        drafts.append(current)

    return drafts


def group_pdf_by_major_heading(document: CanonicalDocument) -> list[ChunkDraft]:
    """Keep noisy PDF subheadings with their numbered top-level section."""

    drafts: list[ChunkDraft] = []
    current = ChunkDraft(section_path="Introduction")

    for block in document.blocks:
        starts_major_section = block.block_type == BlockType.HEADING and block.heading_level == 1
        if starts_major_section:
            if current.blocks:
                drafts.append(current)
            current = ChunkDraft(section_path=block.text, blocks=[block])
            continue

        current.blocks.append(block)

    if current.blocks:
        drafts.append(current)

    return drafts


def group_by_page(document: CanonicalDocument) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    current_page: int | None = None
    current = ChunkDraft(section_path="Page unknown")

    for block in document.blocks:
        page = block.page_number
        if page != current_page:
            if current.blocks:
                drafts.append(current)
            current_page = page
            current = ChunkDraft(section_path=f"Page {page}" if page is not None else "Page unknown")

        current.blocks.append(block)

    if current.blocks:
        drafts.append(current)

    return drafts


def table_section_title(block: ParsedBlock) -> str:
    first_line = next((line.strip() for line in block.text.splitlines() if line.strip()), "Table")
    return first_line[:120]


def group_by_table(document: CanonicalDocument) -> list[ChunkDraft]:
    """Use DOCX table boundaries when a document has no usable heading styles."""

    drafts: list[ChunkDraft] = []
    current = ChunkDraft(section_path="Introduction")

    for block in document.blocks:
        if block.block_type == BlockType.TABLE:
            if current.blocks:
                if current.section_path == "Introduction":
                    # A DOCX title is usually a short paragraph immediately before
                    # the first structured section, so keep it with that section.
                    current = ChunkDraft(section_path=table_section_title(block), blocks=current.blocks + [block])
                    continue
                drafts.append(current)
            current = ChunkDraft(section_path=table_section_title(block), blocks=[block])
        else:
            current.blocks.append(block)

    if current.blocks:
        drafts.append(current)

    return drafts


def draft_text(blocks: list[ParsedBlock]) -> str:
    return "\n".join(block.text for block in blocks if block.text.strip()).strip()


def unique_parts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        collapsed = " ".join(value.split())
        normalized = normalized_label(collapsed)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(collapsed)
    return result


def merge_tiny_drafts(drafts: list[ChunkDraft]) -> list[ChunkDraft]:
    merged: list[ChunkDraft] = []
    pending: ChunkDraft | None = None

    for draft in drafts:
        text = draft_text(draft.blocks)
        if word_count(text) < MIN_CHUNK_WORDS:
            if pending is None:
                pending = draft
            else:
                pending.blocks.extend(draft.blocks)
                pending.section_path = draft.section_path
            continue

        if pending is not None:
            draft.blocks = pending.blocks + draft.blocks
            pending = None
        merged.append(draft)

    if pending is not None:
        if merged:
            merged[-1].blocks.extend(pending.blocks)
        else:
            merged.append(pending)

    return merged


def split_words(text: str, max_words: int = MAX_WORDS, overlap_words: int = OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(0, end - overlap_words)

    return chunks


def pages_for(blocks: list[ParsedBlock]) -> tuple[int | None, int | None]:
    pages = [block.page_number for block in blocks if block.page_number is not None]
    if not pages:
        return None, None
    return min(pages), max(pages)


def normalized_label(value: str) -> str:
    return " ".join(value.split()).casefold()


def is_product_price_header(value: str) -> bool:
    normalized = normalized_label(value)
    return "price" in normalized and ("offer" in normalized or "eligib" in normalized)


def split_product_price_table(draft: ChunkDraft) -> list[tuple[str, str, dict[str, str]]] | None:
    """Split a large price table into product-level retrieval units.

    DOCX tables are intentionally flattened into readable rows by the parser.
    When a table has a three-column header and price-bearing rows, retaining the
    heading, header, and all rows for one product makes each offer retrievable
    without throwing away its eligibility or pricing context.
    """

    tables = [
        block
        for block in draft.blocks
        if block.block_type == BlockType.TABLE and word_count(block.text) > MAX_WORDS
    ]
    if len(tables) != 1:
        return None

    lines = [line.strip() for line in tables[0].text.splitlines() if line.strip()]
    header_index = next(
        (index for index, line in enumerate(lines) if line.count("|") >= 2 and is_product_price_header(line)),
        None,
    )
    if header_index is None:
        return None

    header = lines[header_index]
    prelude = lines[:header_index]
    groups: dict[str, tuple[str, list[str]]] = {}
    order: list[str] = []
    pending_context: list[str] = []

    for line in lines[header_index + 1 :]:
        if not PRICE_ROW_PATTERN.search(line) or line.count("|") < 2:
            pending_context.append(line)
            continue

        first_cell = line.split("|", 1)[0].strip()
        label = " ".join([*pending_context, first_cell]).strip() if pending_context else first_cell
        key = normalized_label(label)
        if key not in groups:
            groups[key] = (label, [])
            order.append(key)
        groups[key][1].append(line)
        pending_context = []

    if len(order) < 3:
        return None

    context = [draft.section_path]
    context.extend(line for line in prelude if normalized_label(line) != normalized_label(draft.section_path))
    results: list[tuple[str, str, dict[str, str]]] = []
    for key in order:
        label, rows = groups[key]
        text = "\n".join([*context, header, f"Product: {label}", *rows])
        results.append(
            (
                f"{draft.section_path} · {label}",
                text,
                {"table_chunking": "product_group", "table_product": label},
            )
        )

    if pending_context:
        text = "\n".join([*context, "Notes", *pending_context])
        results.append(
            (
                f"{draft.section_path} · Notes",
                text,
                {"table_chunking": "table_notes"},
            )
        )

    return results


def normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    normalized: list[list[str]] = []
    for row in rows:
        collapsed = [" ".join(str(cell).split()) for cell in row]
        normalized.append(collapsed + [""] * (width - len(collapsed)))
    return normalized


def repeated_value_ratio(values: list[str]) -> float:
    nonempty = [value for value in values if value]
    if not nonempty:
        return 1.0
    return len(set(nonempty)) / len(nonempty)


def sanitize_chunk_text(text: str, section_path: str | None = None) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    deduped_lines: list[str] = []
    previous_normalized = ""
    section_normalized = normalized_label(section_path or "")

    for line in lines:
        normalized = normalized_label(line)
        if not normalized:
            continue
        if normalized == previous_normalized:
            continue
        deduped_lines.append(line)
        previous_normalized = normalized

    if section_normalized:
        while len(deduped_lines) >= 2:
            first = normalized_label(deduped_lines[0])
            second = normalized_label(deduped_lines[1])
            if first != section_normalized:
                break
            if second == section_normalized or second.startswith(section_normalized):
                deduped_lines.pop(0)
                continue
            break

    return "\n".join(deduped_lines).strip()


def sanitize_section_path(section_path: str) -> str:
    base, separator, suffix = section_path.partition(" · ")
    if not separator:
        base, separator, suffix = section_path.partition(" 路 ")

    if "|" not in base:
        return section_path

    parts = unique_parts([part.strip() for part in base.split("|")])
    cleaned_base = " | ".join(parts)
    return cleaned_base if not separator else f"{cleaned_base}{separator}{suffix}"


def table_group_title(rows: list[list[str]]) -> str | None:
    if not rows:
        return None
    first_row = [cell for cell in rows[0] if cell]
    if not first_row:
        return None
    if len(set(first_row)) == 1:
        return first_row[0]
    return None


def build_column_chunk_label(header_cells: list[str]) -> str:
    parts: list[str] = []
    for cell in header_cells:
        value = " ".join(cell.split())
        if value and value not in parts:
            parts.append(value)
    return " · ".join(parts)


def table_rows_to_text(rows: list[list[str]]) -> str:
    lines: list[str] = []
    for row in rows:
        cells = [cell for cell in row if cell]
        if not cells:
            continue
        if len(cells) == 2:
            lines.append(f"{cells[0]}: {cells[1]}")
        else:
            lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


def build_column_chunk_label(header_cells: list[str]) -> str:
    return " 路 ".join(unique_parts(header_cells))


def is_generic_offer_header(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    header = [normalized_label(cell) for cell in rows[0]]
    if len(header) < 4:
        return False
    return (
        "category" in header[0]
        and "price" in header[1]
        and "quota" in header[2]
        and "validity" in header[3]
    )


def build_offer_row_label(row: list[str]) -> str:
    category = row[0].strip() if len(row) > 0 else ""
    price = row[1].strip() if len(row) > 1 else ""
    quota = row[2].strip() if len(row) > 2 else ""
    parts = [part for part in (category, price) if part]
    if quota and normalized_label(quota) not in {normalized_label(category), normalized_label(price)}:
        parts.append(quota)
    return " | ".join(parts[:3]) or "Offer"


def split_generic_offer_rows(
    draft: ChunkDraft,
    rows: list[list[str]],
    structure_index: int,
) -> list[tuple[str, str, dict[str, str]]] | None:
    if len(rows) < 2 or not is_generic_offer_header(rows):
        return None

    headers = [cell.strip() or f"Field {index + 1}" for index, cell in enumerate(rows[0])]
    outputs: list[tuple[str, str, dict[str, str]]] = []
    for row in rows[1:]:
        label = build_offer_row_label(row)
        lines = [draft.section_path, f"Item: {label}"]
        for index, header in enumerate(headers):
            if index >= len(row):
                continue
            value = row[index].strip()
            if not value:
                continue
            lines.append(f"{header}: {value}")

        if len(lines) <= 2:
            continue

        outputs.append(
            (
                f"{draft.section_path} · {label}",
                sanitize_chunk_text("\n".join(lines).strip(), draft.section_path),
                {
                    "table_chunking": "structured_offer_row",
                    "table_structure_index": str(structure_index),
                    "table_group": label,
                },
            )
        )

    return outputs or None


def direct_table_structure_chunks(
    draft: ChunkDraft,
    rows: list[list[str]],
    structure_index: int,
) -> list[tuple[str, str, dict[str, str]]] | None:
    rows = normalize_table_rows(rows)
    if len(rows) < 3 or len(rows[0]) < 3:
        return None

    generic_offer_rows = split_generic_offer_rows(draft, rows, structure_index)
    if generic_offer_rows is not None:
        return generic_offer_rows

    top_labels = rows[0][1:]
    second_labels = rows[1][1:] if len(rows) > 1 else []
    if (
        len(rows[0]) % 2 == 0
        and len(rows) > 2
        and repeated_value_ratio(top_labels) < 0.6
        and second_labels
        and {"no", "country list"} <= {value.casefold() for value in second_labels if value}
    ):
        grouped_columns: dict[str, list[int]] = {}
        order: list[str] = []
        for column in range(1, len(rows[0]), 2):
            label = rows[0][column].strip()
            if not label:
                continue
            if label not in grouped_columns:
                grouped_columns[label] = []
                order.append(label)
            grouped_columns[label].append(column)

        if len(order) >= 2:
            outputs: list[tuple[str, str, dict[str, str]]] = []
            for label in order:
                lines = [draft.section_path, f"Pass: {label}"]
                for column in grouped_columns[label]:
                    for row in rows[2:]:
                        number = row[column].strip()
                        country = row[column + 1].strip() if column + 1 < len(row) else ""
                        if not country:
                            continue
                        prefix = f"{number}. " if number else ""
                        lines.append(f"{prefix}{country}")
                outputs.append(
                    (
                        f"{draft.section_path} · {label}",
                        sanitize_chunk_text("\n".join(lines).strip(), draft.section_path),
                        {
                            "table_chunking": "paired_column_group",
                            "table_structure_index": str(structure_index),
                            "table_group": label,
                        },
                    )
                )
            return outputs

    header_row_index = 0
    if len(rows) > 1:
        first_distinct_ratio = repeated_value_ratio(rows[0][1:])
        second_distinct_ratio = repeated_value_ratio(rows[1][1:])
        if first_distinct_ratio < second_distinct_ratio:
            header_row_index = 1

    group_title = table_group_title(rows)
    outputs: list[tuple[str, str, dict[str, str]]] = []
    for column in range(1, len(rows[header_row_index])):
        header_cells: list[str] = []
        if group_title:
            header_cells.append(group_title)
        for header_index in range(header_row_index + 1):
            if column >= len(rows[header_index]):
                continue
            cell = rows[header_index][column].strip()
            if not cell or cell == rows[header_index][0].strip():
                continue
            header_cells.append(cell)
        label = build_column_chunk_label(header_cells)
        if not label:
            continue

        lines = [draft.section_path, f"Item: {label}"]
        for row in rows[header_row_index + 1:]:
            if column >= len(row):
                continue
            key = row[0].strip()
            value = row[column].strip()
            if key and value:
                lines.append(f"{key}: {value}")
            elif value:
                lines.append(value)
        if len(lines) <= 2:
            continue
        outputs.append(
            (
                f"{draft.section_path} · {label}",
                sanitize_chunk_text("\n".join(lines).strip(), draft.section_path),
                {
                    "table_chunking": "structured_column_group",
                    "table_structure_index": str(structure_index),
                    "table_group": label,
                },
            )
        )

    return outputs or None


def split_structured_docx_table(draft: ChunkDraft) -> list[tuple[str, str, dict[str, str]]] | None:
    table_blocks = [block for block in draft.blocks if block.block_type == BlockType.TABLE]
    if len(table_blocks) != 1:
        return None

    structures = table_blocks[0].metadata.get("table_structures")
    if not isinstance(structures, list) or not structures:
        return None

    has_nested_or_wide_structure = any(
        isinstance(structure, dict)
        and (
            int(structure.get("depth", 0) or 0) > 0
            or int(structure.get("col_count", 0) or 0) >= 3
        )
        for structure in structures
    )
    if not has_nested_or_wide_structure:
        return None

    outputs: list[tuple[str, str, dict[str, str]]] = []
    for structure_index, structure in enumerate(structures):
        if not isinstance(structure, dict):
            continue
        rows = structure.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        depth = int(structure.get("depth", 0) or 0)
        normalized_rows = normalize_table_rows(rows)

        if depth == 0:
            overview_text = table_rows_to_text(normalized_rows)
            if word_count(overview_text) >= 20:
                outputs.append(
                    (
                        f"{draft.section_path} · Overview",
                        sanitize_chunk_text("\n".join([draft.section_path, overview_text]).strip(), draft.section_path),
                        {
                            "table_chunking": "table_overview",
                            "table_structure_index": str(structure_index),
                        },
                    )
                )
            continue

        structured = direct_table_structure_chunks(draft, normalized_rows, structure_index)
        if structured is not None:
            outputs.extend(structured)
            continue

        fallback_text = table_rows_to_text(normalized_rows)
        if fallback_text and word_count(fallback_text) <= MAX_WORDS:
            title = table_group_title(normalized_rows) or f"Table {structure_index}"
            outputs.append(
                (
                    f"{draft.section_path} · {title}",
                    sanitize_chunk_text("\n".join([draft.section_path, fallback_text]).strip(), draft.section_path),
                    {
                        "table_chunking": "table_subsection",
                        "table_structure_index": str(structure_index),
                    },
                )
            )

    deduped: list[tuple[str, str, dict[str, str]]] = []
    seen: set[tuple[str, str]] = set()
    for section_path, text, metadata in outputs:
        key = (section_path, text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((section_path, text, metadata))

    return deduped or None


def blocks_to_chunk(
    document: CanonicalDocument,
    section_path: str,
    blocks: list[ParsedBlock],
    text: str,
    split_index: int | None = None,
    metadata: dict[str, str] | None = None,
) -> DocumentChunk:
    page_start, page_end = pages_for(blocks)
    clean_section_path = sanitize_section_path(section_path)
    chunk_section = clean_section_path if split_index is None else f"{clean_section_path} (part {split_index + 1})"
    cleaned_text = sanitize_chunk_text(text, clean_section_path)

    return DocumentChunk(
        document_id=document.document_id,
        document_type=document.document_type,
        source_path=document.source_path,
        file_name=document.file_name,
        section_path=chunk_section,
        page_start=page_start,
        page_end=page_end,
        text=cleaned_text,
        source_block_ids=[block.block_id for block in blocks],
        version=document.version,
        metadata={
            "chunker": "defensive_v1",
            "block_count": len(blocks),
            **(metadata or {}),
        },
    )


def chunk_document(document: CanonicalDocument) -> list[DocumentChunk]:
    """Create chunks using structure first, then safer fallbacks.

    This is intentionally defensive: clean SOPs should benefit from headings,
    while messy public PDFs still produce usable page/length chunks.
    """

    table_structured = sum(block.block_type == BlockType.TABLE for block in document.blocks) >= 2
    is_pdf = Path(document.source_path).suffix.lower() == ".pdf"
    has_pdf_major_headings = any(
        block.block_type == BlockType.HEADING and block.heading_level == 1 for block in document.blocks
    )
    if is_pdf and has_pdf_major_headings:
        drafts = group_pdf_by_major_heading(document)
    elif heading_count(document) >= MIN_HEADINGS_FOR_STRUCTURE:
        drafts = group_web_by_major_heading(document) if document.document_type == "web" else group_by_heading(document)
    elif table_structured:
        drafts = group_by_table(document)
    else:
        drafts = group_by_page(document)
    # Table sections in these DOCX knowledge articles are meaningful even when a
    # section is short. Merging them would make source citations misleading.
    if not table_structured and not (is_pdf and has_pdf_major_headings):
        drafts = merge_tiny_drafts(drafts)
    chunks: list[DocumentChunk] = []

    for draft in drafts:
        table_groups = split_product_price_table(draft)
        if table_groups is not None:
            for section_path, text, metadata in table_groups:
                chunks.append(blocks_to_chunk(document, section_path, draft.blocks, text, metadata=metadata))
            continue

        structured_table_groups = split_structured_docx_table(draft)
        if structured_table_groups is not None:
            for section_path, text, metadata in structured_table_groups:
                split_texts = split_words(text)
                for index, split_text in enumerate(split_texts):
                    split_index = index if len(split_texts) > 1 else None
                    chunks.append(
                        blocks_to_chunk(
                            document,
                            section_path,
                            draft.blocks,
                            split_text,
                            split_index=split_index,
                            metadata=metadata,
                        )
                    )
            continue

        text = draft_text(draft.blocks)
        if not text:
            continue

        split_texts = split_words(text)
        for index, split_text in enumerate(split_texts):
            split_index = index if len(split_texts) > 1 else None
            chunks.append(blocks_to_chunk(document, draft.section_path, draft.blocks, split_text, split_index))

    return chunks
