"""Pure rendering and normalization helpers for DOCX table evidence."""

from __future__ import annotations

import re
from typing import TypeAlias


TableOutput: TypeAlias = list[tuple[str, str, dict[str, str]]]

ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff"
SECTION_SEPARATOR = " - "


def normalized_label(value: str) -> str:
    translation = str.maketrans("", "", ZERO_WIDTH_CHARS)
    return " ".join(value.translate(translation).split()).casefold()


def equivalent_table_cell(value: str) -> str:
    """Normalize a visible table label for safe merged-cell de-duplication."""

    return normalized_label(value).rstrip(":")


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


def normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    normalized: list[list[str]] = []
    for row in rows:
        values = [
            "\n".join(" ".join(line.split()) for line in str(cell).splitlines() if line.strip())
            for cell in row
        ]
        normalized.append(values + [""] * (width - len(values)))
    return normalized


def repeated_value_ratio(values: list[str]) -> float:
    nonempty = [value for value in values if value]
    if not nonempty:
        return 1.0
    return len(set(nonempty)) / len(nonempty)


def sanitize_chunk_text(text: str, section_path: str | None = None) -> str:
    translation = str.maketrans("", "", ZERO_WIDTH_CHARS)
    lines = [" ".join(line.translate(translation).split()) for line in text.splitlines() if line.strip()]
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

    list_item_pattern = re.compile(r"^(?:-\s+)?(?:\d+[.)]|[a-zA-Z][.)])\s+")
    index = 0
    while index < len(deduped_lines):
        max_span = min(4, (len(deduped_lines) - index) // 2)
        removed = False
        for span in range(max_span, 1, -1):
            first = deduped_lines[index : index + span]
            second = deduped_lines[index + span : index + (2 * span)]
            if not all(list_item_pattern.match(line) for line in first):
                continue
            if [normalized_label(line) for line in first] != [normalized_label(line) for line in second]:
                continue
            del deduped_lines[index + span : index + (2 * span)]
            removed = True
            break
        if not removed:
            index += 1
    if section_normalized:
        if len(deduped_lines) >= 2 and normalized_label(deduped_lines[0]) == section_normalized:
            repeated_title = normalized_label(deduped_lines[1])
            if repeated_title == f"{section_normalized}: {section_normalized}":
                deduped_lines.pop(1)
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
    for char in ZERO_WIDTH_CHARS:
        section_path = section_path.replace(char, "")
    section_path = re.sub(r"\s+", " ", section_path).strip()
    base, separator, suffix = section_path.partition(SECTION_SEPARATOR)
    if "|" not in base:
        return section_path
    parts = unique_parts([part.strip() for part in base.split("|")])
    cleaned_base = " | ".join(parts)
    cleaned_suffix = re.sub(r"\s+", " ", suffix).strip()
    return cleaned_base if not separator else f"{cleaned_base}{SECTION_SEPARATOR}{cleaned_suffix}"


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
    return SECTION_SEPARATOR.join(unique_parts(header_cells))


def format_table_field(key: str, value: str) -> list[str]:
    value_lines = [" ".join(line.split()) for line in value.splitlines() if line.strip()]
    if len(value_lines) <= 1:
        return [f"{key}: {value_lines[0]}" if value_lines else key]
    bullets = [line.lstrip("-鈥? ").strip() for line in value_lines]
    return [f"{key}:", *[f"- {line}" for line in bullets if line]]


def table_rows_to_text(rows: list[list[str]]) -> str:
    lines: list[str] = []
    for row_index, row in enumerate(rows):
        cells = [cell for cell in row if cell]
        if not cells:
            continue
        if len(cells) == 1 and row_index + 1 < len(rows):
            next_cells = [cell for cell in rows[row_index + 1] if cell]
            if len(next_cells) >= 2 and equivalent_table_cell(cells[0]) == equivalent_table_cell(next_cells[0]):
                continue
        if len(cells) >= 2 and len({equivalent_table_cell(cell) for cell in cells}) == 1:
            lines.append(cells[0].rstrip(":"))
        elif len(cells) == 2:
            lines.extend(format_table_field(cells[0], cells[1]))
        else:
            lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


def is_same_value_row(row: list[str]) -> bool:
    values = [value for value in row if value]
    return bool(values) and len(set(values)) == 1
