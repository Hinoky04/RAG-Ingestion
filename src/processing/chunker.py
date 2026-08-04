from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from src.representation.schemas import BlockType, CanonicalDocument, DocumentChunk, ParsedBlock
from src.processing.table_strategies import direct_table_structure_chunks, split_product_price_table
from src.processing.table_utils import (
    build_column_chunk_label,
    equivalent_table_cell,
    format_table_field,
    is_same_value_row,
    normalize_table_rows,
    normalized_label,
    repeated_value_ratio,
    sanitize_chunk_text,
    sanitize_section_path,
    table_group_title,
    table_rows_to_text,
    unique_parts,
)
from src.processing.docx_table_context import (
    enrich_table_outputs as context_enrich_table_outputs,
    expand_explicit_symbol_legend as context_expand_explicit_symbol_legend,
    explicit_symbol_legend as context_explicit_symbol_legend,
    inline_nested_detail_rows as context_inline_nested_detail_rows,
    inter_table_annotations as context_inter_table_annotations,
    nested_table_notes_by_path as context_nested_table_notes_by_path,
    nested_table_contexts as context_nested_table_contexts,
    parent_rows_around_direct_children as context_parent_rows_around_direct_children,
    remove_inter_table_annotations as context_remove_inter_table_annotations,
    table_structure_anchor as context_table_structure_anchor,
)


MIN_HEADINGS_FOR_STRUCTURE = 3
MAX_WORDS = 350
OVERLAP_WORDS = 50
MIN_CHUNK_WORDS = 25
ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff"
SECTION_SEPARATOR = " - "


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
    cells = [cell.strip() for cell in first_line.split("|") if cell.strip()]
    if len(cells) >= 2 and len({equivalent_table_cell(cell) for cell in cells}) == 1:
        first_line = cells[0].rstrip(":")
    return first_line[:120]


def group_by_table(document: CanonicalDocument) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    current = ChunkDraft(section_path="Introduction")

    for block in document.blocks:
        if block.block_type == BlockType.TABLE:
            if current.blocks:
                if current.section_path == "Introduction":
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


def source_anchor_for(blocks: list[ParsedBlock]) -> str:
    """Create a format-neutral source locator without changing chunk evidence."""
    anchors: list[str] = []
    for block in blocks:
        if block.page_number is not None:
            anchor = f"page:{block.page_number}"
        elif "paragraph_index" in block.metadata:
            anchor = f"paragraph:{block.metadata['paragraph_index']}"
        elif "table_index" in block.metadata:
            anchor = f"table:{block.metadata['table_index']}"
        else:
            continue
        if anchor not in anchors:
            anchors.append(anchor)
    return ", ".join(anchors)


def parent_table_segment_output(
    draft: ChunkDraft,
    rows: list[list[str]],
    structure_index: int | None,
) -> tuple[str, str, dict[str, str]] | None:
    """Render a substantial parent-table narrative segment in source order."""

    text = table_rows_to_text(rows)
    if word_count(text) < 20:
        return None
    label = next((row[0].strip() for row in reversed(rows) if row and row[0].strip()), "Overview")
    metadata = {"table_chunking": "table_parent_segment"}
    if structure_index is not None:
        metadata["table_before_structure_index"] = str(structure_index)
    return (
        f"{draft.section_path}{SECTION_SEPARATOR}{label}",
        sanitize_chunk_text("\n".join([draft.section_path, text]), draft.section_path),
        metadata,
    )


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
    nested_contexts = context_nested_table_contexts(table_blocks[0])
    annotations_by_anchor = context_inter_table_annotations(table_blocks[0])
    symbol_legend = context_explicit_symbol_legend(table_blocks[0])
    notes_by_table_path = context_nested_table_notes_by_path(table_blocks[0]) if symbol_legend else {}
    overview_annotations = annotations_by_anchor
    if notes_by_table_path:
        overview_annotations = {**annotations_by_anchor, "nested_notes": [text for texts in notes_by_table_path.values() for text in texts]}

    # The parser emits nested table structures in document order.  For a
    # narrow, two-by-two detail matrix inside a parent value cell (for example
    # promotional versus normal price), the child is evidence *for that
    # field*, not an independently retrievable table.  Fold only that strict
    # shape into the parent; larger or wider nested tables keep their own
    # chunks and provenance.
    fragments = table_blocks[0].metadata.get("table_fragments")
    nested_fragments = [
        fragment
        for fragment in fragments
        if isinstance(fragment, dict) and fragment.get("kind") == "nested_table"
    ] if isinstance(fragments, list) else []
    fragment_by_structure_index: dict[int, dict[str, object]] = {}
    nested_fragment_index = 0
    normalized_rows_by_index: dict[int, list[list[str]]] = {}
    for structure_index, structure in enumerate(structures):
        if not isinstance(structure, dict):
            continue
        rows = structure.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        normalized_rows_by_index[structure_index] = normalize_table_rows(rows)
        if int(structure.get("depth", 0) or 0) > 0:
            if nested_fragment_index < len(nested_fragments):
                fragment_by_structure_index[structure_index] = nested_fragments[nested_fragment_index]
            nested_fragment_index += 1

    inlined_structure_indexes: set[int] = set()
    for child_index, child_fragment in fragment_by_structure_index.items():
        parent_path = child_fragment.get("parent_table_path")
        child_cell_path = child_fragment.get("cell_path")
        if not isinstance(parent_path, str) or not isinstance(child_cell_path, str):
            continue
        parent_index = next(
            (
                index
                for index, fragment in fragment_by_structure_index.items()
                if fragment.get("table_path") == parent_path
            ),
            None,
        )
        if parent_index is None:
            continue
        merged_rows = context_inline_nested_detail_rows(
            normalized_rows_by_index[parent_index],
            normalized_rows_by_index[child_index],
            child_cell_path,
        )
        if merged_rows is not None:
            normalized_rows_by_index[parent_index] = merged_rows
            inlined_structure_indexes.add(child_index)

    parent_segments: dict[int, list[list[str]]] = {}
    trailing_parent_rows: list[list[str]] | None = None
    sibling_contexts: dict[int, str] = {}
    root_rows = normalized_rows_by_index.get(0)
    if root_rows is not None:
        ordered_parent_rows = context_parent_rows_around_direct_children(
            root_rows,
            fragment_by_structure_index,
            annotations_by_anchor,
        )
        if ordered_parent_rows is not None:
            parent_segments, trailing_parent_rows, sibling_contexts = ordered_parent_rows

    nested_index = 0
    for structure_index, structure in enumerate(structures):
        if not isinstance(structure, dict):
            continue
        rows = structure.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        depth = int(structure.get("depth", 0) or 0)
        normalized_rows = normalized_rows_by_index[structure_index]

        if depth == 0:
            if trailing_parent_rows is not None:
                continue
            normalized_rows = context_remove_inter_table_annotations(normalized_rows, overview_annotations)
            overview_text = table_rows_to_text(normalized_rows)
            if word_count(overview_text) >= 20:
                outputs.extend(context_expand_explicit_symbol_legend([
                    (
                        f"{draft.section_path}{SECTION_SEPARATOR}Overview",
                        sanitize_chunk_text("\n".join([draft.section_path, overview_text]).strip(), draft.section_path),
                        {
                            "table_chunking": "table_overview",
                            "table_structure_index": str(structure_index),
                        },
                    )
                ], symbol_legend))
            continue

        parent_segment = parent_table_segment_output(
            draft,
            parent_segments.get(structure_index, []),
            structure_index,
        )
        if parent_segment is not None:
            outputs.extend(context_expand_explicit_symbol_legend([parent_segment], symbol_legend))

        context = nested_contexts[nested_index] if nested_index < len(nested_contexts) else None
        nested_index += 1
        if context is None:
            context = sibling_contexts.get(structure_index)
        if structure_index in inlined_structure_indexes:
            continue
        child_fragment = fragment_by_structure_index.get(structure_index, {})
        table_path = child_fragment.get("table_path") if isinstance(child_fragment, dict) else None
        annotations = (
            notes_by_table_path.get(table_path, [])
            if isinstance(table_path, str) and table_path in notes_by_table_path
            else annotations_by_anchor.get(normalized_label(context_table_structure_anchor(normalized_rows)), [])
        )

        structured = direct_table_structure_chunks(draft, normalized_rows, structure_index)
        if structured is not None:
            outputs.extend(context_expand_explicit_symbol_legend(
                context_enrich_table_outputs(structured, draft, context, annotations),
                symbol_legend,
            ))
            continue

        fallback_text = table_rows_to_text(normalized_rows)
        if fallback_text:
            title = table_group_title(normalized_rows) or f"Table {structure_index}"
            fallback = context_enrich_table_outputs([
                (
                    f"{draft.section_path}{SECTION_SEPARATOR}{title}",
                    sanitize_chunk_text("\n".join([draft.section_path, fallback_text]).strip(), draft.section_path),
                    {
                        "table_chunking": "table_subsection",
                        "table_structure_index": str(structure_index),
                    },
                )
            ], draft, context, annotations)
            outputs.extend(context_expand_explicit_symbol_legend(fallback, symbol_legend))

    if trailing_parent_rows is not None:
        trailing_segment = parent_table_segment_output(draft, trailing_parent_rows, None)
        if trailing_segment is not None:
            outputs.extend(context_expand_explicit_symbol_legend([trailing_segment], symbol_legend))

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
    chunk_identity = "\x1f".join([document.document_id, chunk_section, cleaned_text])
    chunk_id = f"chunk_{hashlib.sha256(chunk_identity.encode('utf-8')).hexdigest()[:20]}"

    return DocumentChunk(
        chunk_id=chunk_id,
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
            "chunker": "defensive_v2",
            "block_count": len(blocks),
            "source_checksum": str(document.metadata.get("source_checksum", "")),
            "source_key": str(document.metadata.get("source_key", Path(document.file_name).stem.casefold())),
            "source_anchor": source_anchor_for(blocks),
            **(metadata or {}),
        },
    )


def chunk_document(document: CanonicalDocument) -> list[DocumentChunk]:
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
