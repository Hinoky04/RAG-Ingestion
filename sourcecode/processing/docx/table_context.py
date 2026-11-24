"""Recover labels and notes that sit next to nested DOCX tables.

A child table's label may be the paragraph before it, while its notes may come
after it in the same cell. XML paths and order are used only when that nearby
relationship is clear; otherwise the extra context is left alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sourcecode.representation.schemas import ParsedBlock
from sourcecode.processing.docx.table_utils import TableOutput, normalized_label, sanitize_chunk_text

if TYPE_CHECKING:
    from sourcecode.processing.chunker import ChunkDraft


_SYMBOL_LEGEND_PATTERN = re.compile(
    r"(?P<symbol>[✅✖🔵])\ufe0f?[\s\u200b\ufeff]*"
    r"(?P<label>Eligible\s+with\s+replacement\s+of\s+existing\s+subscription|Not\s+eligible|Eligible)(?!\w)",
    re.IGNORECASE,
)


def explicit_symbol_legend(table_block: ParsedBlock) -> dict[str, str]:
    """Read symbol meanings only when the table explicitly supplies them."""
    legend: dict[str, str] = {}
    for match in _SYMBOL_LEGEND_PATTERN.finditer(table_block.text):
        symbol = match.group("symbol")
        label = " ".join(match.group("label").split())
        legend[symbol] = label
    return legend


def expand_explicit_symbol_legend(outputs: TableOutput, legend: dict[str, str]) -> TableOutput:
    """Keep visual markers while making explicitly defined states searchable."""
    if not legend:
        return outputs

    expanded: TableOutput = []
    for section_path, text, metadata in outputs:
        enriched = text
        for symbol, label in legend.items():
            token = re.escape(symbol) + r"\ufe0f?"
            # Legend may already have this label. Do not add second time.
            pattern = re.compile(
                rf"(?P<token>{token})(?![\s\u200b\ufeff]*{re.escape(label)})",
                re.IGNORECASE,
            )
            enriched = pattern.sub(lambda match: f"{match.group('token')} {label}", enriched)
        expanded.append((section_path, sanitize_chunk_text(enriched), {**metadata, "table_symbol_legend": "explicit"}))
    return expanded


def inline_nested_detail_rows(parent_rows: list[list[str]], child_rows: list[list[str]], child_cell_path: str) -> list[list[str]] | None:
    """Inline a tiny nested header/value matrix into its parent table field."""
    if (
        len(parent_rows) < 1 or any(len(row) != 2 for row in parent_rows)
        or len(child_rows) != 2
        or any(len(row) != 2 or not all(cell.strip() for cell in row) for row in child_rows)
        or len(" ".join(cell for row in child_rows for cell in row).split()) > 50
    ):
        return None
    match = re.search(r"\.r(\d+)c(\d+)$", child_cell_path)
    if match is None:
        return None
    row_index, column_index = (int(value) - 1 for value in match.groups())
    if row_index >= len(parent_rows) or column_index != 1:
        return None
    details = [f"{header}: {' '.join(value.split())}" for header, value in zip(child_rows[0], child_rows[1])]
    merged = [row.copy() for row in parent_rows]
    merged[row_index][column_index] = "\n".join([merged[row_index][column_index], *details]).strip()
    return merged


def nested_table_contexts(table_block: ParsedBlock) -> list[str | None]:
    """Use only a nearby compact label as child-table context, never free prose."""
    fragments = table_block.metadata.get("table_fragments")
    if not isinstance(fragments, list):
        return []
    contexts: list[str | None] = []
    for fragment in fragments:
        if not isinstance(fragment, dict) or fragment.get("kind") != "nested_table":
            continue
        cell_path, ordinal = fragment.get("cell_path"), fragment.get("xml_ordinal")
        if not isinstance(cell_path, str) or not isinstance(ordinal, int):
            contexts.append(None)
            continue
        candidates = [item for item in fragments if isinstance(item, dict) and item.get("kind") == "paragraph" and item.get("cell_path") == cell_path and isinstance(item.get("xml_ordinal"), int) and item["xml_ordinal"] < ordinal]
        if not candidates:
            contexts.append(None)
            continue
        candidate = max(candidates, key=lambda item: int(item["xml_ordinal"]))
        text = " ".join(str(candidate.get("text", "")).split()).strip()
        style = str(candidate.get("style", "")).casefold()
        is_numbered_caption = bool(re.match(r"^\d+[.)]\s+\S+", text))
        is_caption_style = "list" in style or "heading" in style
        is_compact_standalone_label = len(text.split()) <= 8 and not re.search(r"[.!?]$", text)
        contexts.append(text if text and len(text) <= 120 and len(text.split()) <= 14 and (is_numbered_caption or is_caption_style or is_compact_standalone_label) else None)
    return contexts


def table_structure_anchor(rows: list[list[str]]) -> str:
    labels: list[str] = []
    for row in rows[:2]:
        for cell in row:
            label = " ".join(cell.split())
            if label and normalized_label(label) not in {normalized_label(value) for value in labels}:
                labels.append(label)
    return " | ".join(labels[:3])[:240]


def inter_table_annotations(table_block: ParsedBlock) -> dict[str, list[str]]:
    """Attach trailing cell paragraphs to the nested table immediately before them."""
    fragments = table_block.metadata.get("table_fragments")
    if not isinstance(fragments, list):
        return {}
    by_cell: dict[str, list[dict[str, object]]] = {}
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        cell_path, ordinal = fragment.get("cell_path"), fragment.get("xml_ordinal")
        if isinstance(cell_path, str) and isinstance(ordinal, int):
            by_cell.setdefault(cell_path, []).append(fragment)
    annotations: dict[str, list[str]] = {}
    for cell_fragments in by_cell.values():
        previous_anchor: str | None = None
        ordered = sorted(cell_fragments, key=lambda item: int(item["xml_ordinal"]))
        for index, fragment in enumerate(ordered):
            if fragment.get("kind") == "nested_table":
                anchor = fragment.get("anchor")
                previous_anchor = anchor if isinstance(anchor, str) else None
                continue
            if fragment.get("kind") != "paragraph" or previous_anchor is None:
                continue
            if any(item.get("kind") == "nested_table" for item in ordered[index + 1:]):
                continue
            text = "\n".join(line.strip() for line in str(fragment.get("text", "")).splitlines() if line.strip())
            if text:
                annotations.setdefault(normalized_label(previous_anchor), []).append(text)
    return annotations


def nested_table_notes_by_path(table_block: ParsedBlock) -> dict[str, list[str]]:
    """Get Notes text for the child table directly before it."""
    # Same parent cell is required. Otherwise repeated headings can take wrong note.
    fragments = table_block.metadata.get("table_fragments")
    if not isinstance(fragments, list):
        return {}

    by_cell: dict[str, list[dict[str, object]]] = {}
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        cell_path, ordinal = fragment.get("cell_path"), fragment.get("xml_ordinal")
        if isinstance(cell_path, str) and isinstance(ordinal, int):
            by_cell.setdefault(cell_path, []).append(fragment)

    annotations: dict[str, list[str]] = {}
    for cell_fragments in by_cell.values():
        ordered = sorted(cell_fragments, key=lambda item: int(item["xml_ordinal"]))
        for index, fragment in enumerate(ordered):
            if fragment.get("kind") != "nested_table":
                continue
            table_path = fragment.get("table_path")
            if not isinstance(table_path, str):
                continue
            following: list[str] = []
            for candidate in ordered[index + 1:]:
                if candidate.get("kind") == "nested_table":
                    break
                if candidate.get("kind") != "paragraph":
                    continue
                text = "\n".join(line.strip() for line in str(candidate.get("text", "")).splitlines() if line.strip())
                if text:
                    following.append(text)
            note_start = next((position for position, text in enumerate(following) if normalized_label(text).startswith("notes")), None)
            if note_start is not None:
                annotations[table_path] = following[note_start:]
    return annotations


def remove_inter_table_annotations(rows: list[list[str]], annotations: dict[str, list[str]]) -> list[list[str]]:
    """Prevent a note from appearing in both the parent overview and its child chunk."""
    lines = {normalized_label(line) for texts in annotations.values() for text in texts for line in text.splitlines()}
    return [["\n".join(line for line in cell.splitlines() if normalized_label(line) not in lines).strip() for cell in row] for row in rows]


def parent_rows_around_direct_children(
    parent_rows: list[list[str]],
    fragments_by_structure_index: dict[int, dict[str, object]],
    annotations: dict[str, list[str]],
) -> tuple[dict[int, list[list[str]]], list[list[str]], dict[int, str]] | None:
    """Keep parent rows beside their child tables in document order."""
    # Simple parent/child table still uses normal overview path.

    child_locations: list[tuple[int, int]] = []
    for structure_index, fragment in fragments_by_structure_index.items():
        if fragment.get("parent_table_path") != "root":
            continue
        cell_path = fragment.get("cell_path")
        if not isinstance(cell_path, str):
            return None
        match = re.fullmatch(r"root\.r(\d+)c\d+", cell_path)
        if match is None:
            return None
        child_locations.append((structure_index, int(match.group(1)) - 1))

    distinct_child_rows = {row_index for _, row_index in child_locations}
    parent_narrative_rows = len(parent_rows) - len(distinct_child_rows)
    if len(distinct_child_rows) < 3 or parent_narrative_rows < 2:
        return None

    cleaned_rows = remove_inter_table_annotations(parent_rows, annotations)
    before_child: dict[int, list[list[str]]] = {}
    child_contexts: dict[int, str] = {}
    cursor = 0
    for structure_index, row_index in sorted(child_locations, key=lambda item: item[1]):
        if row_index < cursor - 1 or row_index >= len(cleaned_rows):
            return None
        if row_index == cursor - 1:
            before_child[structure_index] = []
        else:
            before_child[structure_index] = cleaned_rows[cursor : row_index + 1]
            cursor = row_index + 1
        label = next((cell.strip() for cell in cleaned_rows[row_index] if cell.strip()), "")
        if label:
            child_contexts[structure_index] = label
    return before_child, cleaned_rows[cursor:], child_contexts


def enrich_table_outputs(outputs: TableOutput, draft: "ChunkDraft", parent_context: str | None, annotations: list[str]) -> TableOutput:
    """Repeat only the context needed to interpret a chunk outside its source table."""
    contextualized = outputs
    if parent_context:
        contextualized = []
        for section_path, text, metadata in outputs:
            suffix = section_path.removeprefix(f"{draft.section_path} - ")
            title = f"{draft.section_path} - {parent_context}"
            if suffix:
                title = f"{title} - {suffix}"
            lines = text.splitlines()
            if lines and normalized_label(lines[0]) == normalized_label(draft.section_path):
                lines.insert(1, f"Table context: {parent_context}")
            else:
                lines.insert(0, f"Table context: {parent_context}")
            contextualized.append((title, sanitize_chunk_text("\n".join(lines), draft.section_path), {**metadata, "table_parent_context": parent_context}))
    if not annotations:
        return contextualized
    note_lines = ["Table notes:", *annotations]
    return [(section_path, sanitize_chunk_text("\n".join([*text.splitlines(), *note_lines]), draft.section_path), {**metadata, "table_note_count": str(len(annotations))}) for section_path, text, metadata in contextualized]
