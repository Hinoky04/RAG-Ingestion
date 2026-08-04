"""Small, dependency-free registry primitives for DOCX table chunk strategies."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Callable, TypeAlias

from src.processing.table_utils import (
    SECTION_SEPARATOR,
    TableOutput,
    build_column_chunk_label,
    format_table_field,
    is_same_value_row,
    normalize_table_rows,
    normalized_label,
    repeated_value_ratio,
    sanitize_chunk_text,
    table_group_title,
)
from src.representation.schemas import BlockType

if TYPE_CHECKING:
    from src.processing.chunker import ChunkDraft


TableChunkOutput: TypeAlias = TableOutput
TableStrategyHandler: TypeAlias = Callable[["ChunkDraft", list[list[str]], int], TableChunkOutput | None]
MAX_WORDS = 350
PRICE_ROW_PATTERN = re.compile(r"\bRM\s*\d", re.IGNORECASE)


@dataclass(frozen=True)
class TableStrategy:
    """A named table-chunking strategy."""

    name: str
    handler: TableStrategyHandler


def first_matching_strategy(
    strategies: tuple[TableStrategy, ...],
    draft: "ChunkDraft",
    rows: list[list[str]],
    structure_index: int,
) -> TableChunkOutput | None:
    """Return the first matching table strategy."""

    for strategy in strategies:
        outputs = strategy.handler(draft, rows, structure_index)
        if outputs is not None:
            return outputs
    return None


def split_product_price_table(draft: "ChunkDraft") -> TableChunkOutput | None:
    """Split a long product/price table without separating a product from its offers."""
    tables = [block for block in draft.blocks if block.block_type == BlockType.TABLE and len(block.text.split()) > MAX_WORDS]
    if len(tables) != 1:
        return None
    lines = [line.strip() for line in tables[0].text.splitlines() if line.strip()]
    header_index = next((index for index, line in enumerate(lines) if line.count("|") >= 2 and "price" in normalized_label(line) and ("offer" in normalized_label(line) or "eligib" in normalized_label(line))), None)
    if header_index is None:
        return None
    header, prelude = lines[header_index], lines[:header_index]
    groups: dict[str, tuple[str, list[str]]] = {}
    order: list[str] = []
    pending_context: list[str] = []
    for line in lines[header_index + 1:]:
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
    context = [draft.section_path, *(line for line in prelude if normalized_label(line) != normalized_label(draft.section_path))]
    results: TableChunkOutput = []
    for key in order:
        label, rows = groups[key]
        results.append((f"{draft.section_path}{SECTION_SEPARATOR}{label}", "\n".join([*context, header, f"Product: {label}", *rows]), {"table_chunking": "product_group", "table_product": label}))
    if pending_context:
        results.append((f"{draft.section_path}{SECTION_SEPARATOR}Notes", "\n".join([*context, "Notes", *pending_context]), {"table_chunking": "table_notes"}))
    return results


def split_two_column_parallel_description(
    draft: "ChunkDraft",
    rows: list[list[str]],
    structure_index: int,
) -> TableChunkOutput | None:
    """Keep two side-by-side explanatory fields separate and labelled.

    This is deliberately narrower than a generic two-column table: each
    value must contain multiple paragraphs, which is the reliable DOCX signal
    for two independent prose/list descriptions rather than key/value rows.
    """

    if len(rows) != 2 or any(len(row) != 2 for row in rows):
        return None
    headers = [cell.strip() for cell in rows[0]]
    values = [cell.strip() for cell in rows[1]]
    if not all(headers) or not all(values):
        return None
    if any(len(header.split()) > 12 for header in headers):
        return None
    if any("\n" not in value for value in values):
        return None

    lines = [draft.section_path, f"Table: {' | '.join(headers)}"]
    for header, value in zip(headers, values):
        lines.extend(format_table_field(header, value))
    return [
        (
            f"{draft.section_path}{SECTION_SEPARATOR}{' | '.join(headers)}",
            sanitize_chunk_text("\n".join(lines), draft.section_path),
            {
                "table_chunking": "two_column_parallel_description",
                "table_structure_index": str(structure_index),
            },
        )
    ]


def split_hierarchical_row_matrix(
    draft: "ChunkDraft",
    rows: list[list[str]],
    structure_index: int,
) -> TableChunkOutput | None:
    """Render a dense, multi-level numeric matrix as complete row records.

    The rule is structural: a repeated multi-row header followed by at least
    four unique, fully populated records.  It prevents a price matrix from
    being separated into unrelated column chunks.
    """

    if len(rows) < 7 or len(rows[0]) < 4 or any(len(row) != len(rows[0]) for row in rows):
        return None

    data_start: int | None = None
    for index in range(3, len(rows) - 3):
        records = rows[index:]
        keys = [row[0].strip() for row in records]
        if not all(keys) or len({normalized_label(key) for key in keys}) != len(keys):
            continue
        if any(any(not value.strip() for value in row) for row in records):
            continue
        candidate_values = [value.strip() for row in records for value in row[1:]]
        candidate_numeric_values = sum(
            bool(re.fullmatch(r"(?:RM\s*)?\d+(?:\.\d+)?", normalized_label(value), re.IGNORECASE))
            for value in candidate_values
        )
        if candidate_numeric_values / len(candidate_values) < 0.95:
            continue
        data_start = index
        break
    if data_start is None:
        return None

    records = rows[data_start:]
    value_cells = [value.strip() for row in records for value in row[1:]]
    numeric_values = sum(bool(re.fullmatch(r"(?:RM\s*)?\d+(?:\.\d+)?", normalized_label(value), re.IGNORECASE)) for value in value_cells)
    if numeric_values / len(value_cells) < 0.95:
        return None

    field_paths = [" ".join(rows[0][0].split())]
    record_fields = [field_paths[0]]
    first_column_header = normalized_label(rows[0][0])
    for column in range(1, len(rows[0])):
        parts: list[str] = []
        for header_row in rows[:data_start]:
            value = " ".join(header_row[column].split())
            if not value or normalized_label(value) == first_column_header:
                continue
            if not parts or normalized_label(value) != normalized_label(parts[-1]):
                parts.append(value)
        if not parts:
            return None
        field_paths.append(" > ".join(parts))
        record_fields.append(parts[-1])

    value_path_parts = [path.split(" > ") for path in field_paths[1:]]
    shared_scope: list[str] = []
    for parts in zip(*value_path_parts):
        if len({normalized_label(part) for part in parts}) != 1:
            break
        shared_scope.append(parts[0])

    lines = [draft.section_path, f"Table: {field_paths[0]} matrix"]
    if shared_scope:
        lines.append(f"Scope: {' > '.join(shared_scope)}")
    lines.append(f"Fields: {' | '.join(record_fields)}")
    for row in records:
        fields = [f"{field}: {value.strip()}" for field, value in zip(record_fields, row)]
        lines.append("- " + " | ".join(fields))
    return [
        (
            f"{draft.section_path}{SECTION_SEPARATOR}{field_paths[0]} matrix",
            sanitize_chunk_text("\n".join(lines), draft.section_path),
            {
                "table_chunking": "hierarchical_row_matrix",
                "table_structure_index": str(structure_index),
                "table_record_count": str(len(records)),
            },
        )
    ]


def is_row_mapping_table(rows: list[list[str]]) -> bool:
    """Recognise a large, short-cell matrix whose row is the evidence unit."""

    if len(rows) < 8 or not 3 <= len(rows[0]) <= 4:
        return False
    headers = [cell.strip() for cell in rows[0]]
    if not all(headers) or any(len(row) != len(headers) for row in rows[1:]):
        return False
    records = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    if len(records) < 7:
        return False
    leading_values = [row[0].strip() for row in records]
    if sum(bool(value) for value in leading_values) / len(records) < 0.85:
        return False
    normalized_leading = [normalized_label(value) for value in leading_values if value]
    if len(set(normalized_leading)) / len(normalized_leading) < 0.8:
        return False
    nonempty_cells = [cell for row in records for cell in row if cell.strip()]
    return sum(len(cell.split()) for cell in nonempty_cells) / len(nonempty_cells) <= 8


def split_row_mapping_table(
    draft: "ChunkDraft", rows: list[list[str]], structure_index: int
) -> TableChunkOutput | None:
    """Chunk a cross-column mapping as compact windows without losing row links."""

    if not is_row_mapping_table(rows):
        return None
    headers = [cell.strip() for cell in rows[0]]
    indexed_records = [(index, row) for index, row in enumerate(rows[1:], start=1) if any(cell.strip() for cell in row)]
    mapping_records = [(index, row) for index, row in indexed_records if sum(bool(cell.strip()) for cell in row) >= 2]
    outputs: TableChunkOutput = []
    for start in range(0, len(mapping_records), 5):
        window = mapping_records[start : start + 5]
        lines = [draft.section_path, f"Mapping: {' | '.join(headers)}"]
        for _, row in window:
            fields = [f"{header}: {value.strip()}" for header, value in zip(headers, row) if value.strip()]
            if fields:
                lines.append("- " + " | ".join(fields))
        first_row, last_row = window[0][0], window[-1][0]
        outputs.append((
            f"{draft.section_path} - Plan mappings {first_row}-{last_row}",
            sanitize_chunk_text("\n".join(lines), draft.section_path),
            {"table_chunking": "row_mapping_window", "table_structure_index": str(structure_index), "table_row_start": str(first_row), "table_row_end": str(last_row)},
        ))
    sparse_by_columns: dict[tuple[int, ...], list[str]] = {}
    for _, row in indexed_records:
        populated_columns = tuple(index for index, value in enumerate(row) if value.strip())
        if len(populated_columns) == 1:
            column = populated_columns[0]
            sparse_by_columns.setdefault(populated_columns, []).append(row[column].strip())
    for populated_columns, values in sparse_by_columns.items():
        header = headers[populated_columns[0]]
        outputs.append((
            f"{draft.section_path} - {header} additional list",
            sanitize_chunk_text("\n".join([draft.section_path, f"Additional listed {header}:", *[f"- {value}" for value in values]]), draft.section_path),
            {"table_chunking": "row_mapping_sparse_list", "table_structure_index": str(structure_index), "table_group": header},
        ))
    return outputs or None


def split_paired_country_columns(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Preserve repeated ``No | Country List`` column pairs as pass-level evidence."""
    if len(rows) < 3 or len(rows[0]) % 2 != 0:
        return None
    top_labels, second_labels = rows[0][1:], rows[1][1:]
    if repeated_value_ratio(top_labels) >= 0.6 or not second_labels or not {"no", "country list"} <= {value.casefold() for value in second_labels if value}:
        return None
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for column in range(0, len(rows[0]) - 1, 2):
        label = rows[0][column].strip()
        if not label:
            continue
        if label not in groups:
            groups[label] = []; order.append(label)
        groups[label].append(column)
    if len(order) < 2:
        return None
    outputs: TableChunkOutput = []
    for label in order:
        lines = [draft.section_path, f"Pass: {label}"]
        for column in groups[label]:
            for row in rows[2:]:
                number = row[column].strip()
                country = row[column + 1].strip() if column + 1 < len(row) else ""
                if country:
                    lines.append(f"{number}. {country}" if number else country)
        outputs.append((f"{draft.section_path} - {label}", sanitize_chunk_text("\n".join(lines).strip(), draft.section_path), {"table_chunking": "paired_column_group", "table_structure_index": str(structure_index), "table_group": label}))
    return outputs


def split_two_column_comparison(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Keep paired comparison values together when a two-column table proves their grouping."""
    if len(rows) < 3 or max(len(row) for row in rows) != 2:
        return None
    lines = [draft.section_path]
    found_comparison = False
    index = 0
    while index < len(rows):
        row = rows[index]
        if not is_same_value_row(row):
            return None
        group = next(value for value in row if value)
        index += 1
        if index < len(rows) and is_same_value_row(rows[index]):
            value = next(value for value in rows[index] if value)
            if normalized_label(value) != normalized_label(group):
                lines.append(f"{group}: {value}")
                found_comparison = True
            index += 1
            continue
        if index + 1 >= len(rows):
            return None
        headers, values = rows[index], rows[index + 1]
        next_index = index + 2
        if not all(headers) or not all(values) or next_index < len(rows) and not is_same_value_row(rows[next_index]):
            return None
        lines.append(f"{group}:")
        for header, value in zip(headers, values):
            lines.extend(format_table_field(header, value))
        found_comparison = True
        index = next_index
    if not found_comparison:
        return None
    return [(f"{draft.section_path}{SECTION_SEPARATOR}Comparison", sanitize_chunk_text("\n".join(lines), draft.section_path), {"table_chunking": "two_column_comparison", "table_structure_index": str(structure_index)})]


def is_long_two_column_reference_table(rows: list[list[str]]) -> bool:
    return len(rows) >= 8 and max(len(row) for row in rows) == 2 and all(len(row) == 2 and row[0] and row[1] for row in rows) and any(len(row[1]) >= 240 for row in rows)


def split_long_two_column_reference_rows(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Create one evidence unit per entry for a long two-column reference table."""
    if not is_long_two_column_reference_table(rows):
        return None
    return [
        (f"{draft.section_path}{SECTION_SEPARATOR}{label}", sanitize_chunk_text("\n".join([draft.section_path, f"Item: {label}", value]), draft.section_path), {"table_chunking": "long_two_column_reference_row", "table_structure_index": str(structure_index), "table_row_index": str(row_index), "table_group": label})
        for row_index, (label, value) in enumerate(rows, start=1)
    ]


def is_repeated_rate_schedule_table(rows: list[list[str]]) -> bool:
    if len(rows) < 5 or len(rows[0]) < 3 or not all(rows[0]):
        return False
    keys = [row[0] for row in rows[1:] if row and row[0]]
    non_key_values = [value for row in rows[1:] for value in row[1:] if value]
    charge_values = [row[-1] for row in rows[1:] if row and row[-1]]
    range_count = sum(bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:kb|mb|gb|tb)\b", value, re.IGNORECASE)) for value in non_key_values)
    money_count = sum(bool(re.search(r"\bRM\s*\d", value, re.IGNORECASE)) for value in non_key_values)
    return len(keys) >= 4 and repeated_value_ratio(keys) <= 0.75 and range_count >= 3 and money_count >= 3 and len(charge_values) >= 4 and repeated_value_ratio(charge_values) <= 0.5


def split_repeated_rate_schedule_table(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Preserve row-level relationships for tables with repeated record keys."""
    if not is_repeated_rate_schedule_table(rows):
        return None
    headers = rows[0]
    records = [draft.section_path, f"Table: {' | '.join(headers)}"]
    for row in rows[1:]:
        values = row + [""] * (len(headers) - len(row))
        fields = [f"{header}: {value}" for header, value in zip(headers, values) if value]
        if fields:
            records.append(" | ".join(fields))
    if len(records) <= 2:
        return None
    label = headers[1] if len(headers) > 1 and headers[1] else headers[0]
    return [(f"{draft.section_path}{SECTION_SEPARATOR}{label}", sanitize_chunk_text("\n".join(records), draft.section_path), {"table_chunking": "repeated_rate_schedule", "table_structure_index": str(structure_index)})]


def is_bundle_partner_table(rows: list[list[str]]) -> bool:
    if len(rows) < 3 or len(rows[0]) < 2:
        return False
    first_label, second_label = normalized_label(rows[0][0]), normalized_label(rows[1][0])
    return "bundle" in first_label and ("streaming partner" in second_label or "streaming partners" in second_label or "partner" in second_label) and any(cell.strip() for cell in rows[0][1:]) and any(cell.strip() for cell in rows[1][1:])


def make_bundle_partner_label(bundle: str, partner: str, row_lookup: dict[str, str], seen_labels: set[str]) -> str:
    base = " | ".join(part for part in (bundle, partner) if part).strip() or "Bundle Offer"
    if base not in seen_labels:
        seen_labels.add(base)
        return base
    for key in ("Monthly cycle", "Access", "CelcomDigi Price (RM)", "Quota (5G+4G)"):
        value = " ".join(row_lookup.get(normalized_label(key), "").split())
        if value:
            candidate = f"{base} | {value}"
            if candidate not in seen_labels:
                seen_labels.add(candidate)
                return candidate
    suffix = 2
    while True:
        candidate = f"{base} | Option {suffix}"
        if candidate not in seen_labels:
            seen_labels.add(candidate)
            return candidate
        suffix += 1


def split_bundle_partner_columns(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    if not is_bundle_partner_table(rows):
        return None
    outputs: TableChunkOutput = []
    seen_labels: set[str] = set()
    for column in range(1, len(rows[0])):
        bundle = rows[0][column].strip() if column < len(rows[0]) else ""
        partner = rows[1][column].strip() if column < len(rows[1]) else ""
        if not bundle and not partner:
            continue
        row_lookup: dict[str, str] = {}
        lines = [draft.section_path]
        if bundle:
            lines.append(f"Bundle: {bundle}")
        if partner:
            lines.append(f"Partner: {partner}")
        for row in rows[2:]:
            key = row[0].strip() if row else ""
            if not key or column >= len(row):
                continue
            value = row[column].strip()
            if value:
                row_lookup[normalized_label(key)] = value
                lines.extend(format_table_field(key, value))
        if len(lines) <= 3:
            continue
        label = make_bundle_partner_label(bundle, partner, row_lookup, seen_labels)
        outputs.append((f"{draft.section_path}{SECTION_SEPARATOR}{label}", sanitize_chunk_text("\n".join(lines).strip(), draft.section_path), {"table_chunking": "bundle_partner_column", "table_structure_index": str(structure_index), "table_group": bundle or partner or label, "table_partner": partner}))
    return outputs or None


def is_generic_offer_header(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    header = [normalized_label(cell) for cell in rows[0]]
    return len(header) >= 4 and "category" in header[0] and "price" in header[1] and "quota" in header[2] and "validity" in header[3]


def build_offer_row_label(row: list[str]) -> str:
    category, price, quota = (row[index].strip() if len(row) > index else "" for index in range(3))
    parts = [part for part in (category, price) if part]
    if quota and normalized_label(quota) not in {normalized_label(category), normalized_label(price)}:
        parts.append(quota)
    return " | ".join(parts[:3]) or "Offer"


def split_generic_offer_rows(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    if len(rows) < 2 or not is_generic_offer_header(rows):
        return None
    headers = [cell.strip() or f"Field {index + 1}" for index, cell in enumerate(rows[0])]
    outputs: TableChunkOutput = []
    for row in rows[1:]:
        label = build_offer_row_label(row)
        lines = [draft.section_path, f"Item: {label}"]
        for index, header in enumerate(headers):
            if index >= len(row):
                continue
            value = row[index].strip()
            if value:
                lines.extend(format_table_field(header, value))
        if len(lines) > 2:
            outputs.append((f"{draft.section_path}{SECTION_SEPARATOR}{label}", sanitize_chunk_text("\n".join(lines).strip(), draft.section_path), {"table_chunking": "structured_offer_row", "table_structure_index": str(structure_index), "table_group": label}))
    return outputs or None


def split_grouped_three_column_table(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Keep merged first-column groups tied to their plan/update rows."""
    if len(rows) < 3 or any(len(row) != 3 for row in rows):
        return None
    headers = [cell.strip() for cell in rows[0]]
    if not all(headers):
        return None
    data_group_values = [row[0].strip() for row in rows[1:] if row[0].strip()]
    has_repeated_merged_group = len(set(normalized_label(value) for value in data_group_values)) < len(data_group_values)
    if "group" not in normalized_label(headers[0]) and not has_repeated_merged_group:
        return None
    groups: dict[str, list[list[str]]] = {}
    order: list[str] = []
    for row in rows[1:]:
        group, item, update = (cell.strip() for cell in row)
        if not group or not item:
            return None
        key = normalized_label(group)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append([item, update])
    if len(order) < 2:
        return None
    outputs: TableChunkOutput = []
    for key in order:
        group = next(row[0] for row in rows[1:] if normalized_label(row[0]) == key)
        lines = [draft.section_path, f"{headers[0]}: {group}"]
        for item, update in groups[key]:
            lines.append(f"{headers[1]}: {item}")
            lines.extend(format_table_field(headers[2], update))
        outputs.append((f"{draft.section_path}{SECTION_SEPARATOR}{group}", sanitize_chunk_text("\n".join(lines), draft.section_path), {"table_chunking": "grouped_three_column_rows", "table_structure_index": str(structure_index), "table_group": group}))
    return outputs


def split_small_relational_table(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Keep a compact three-column matrix intact instead of separating columns."""
    if len(rows) < 2 or len(rows) > 6 or any(len(row) != 3 for row in rows):
        return None
    headers = [cell.strip() for cell in rows[0]]
    if not all(headers) or any(not row[0].strip() for row in rows[1:]):
        return None
    header_text = normalized_label(" ".join(headers))
    if "payment" not in header_text or not ({"registration", "bill", "charged"} & set(header_text.split())):
        return None
    if len({normalized_label(row[0]) for row in rows[1:]}) != len(rows) - 1:
        return None
    lines = [draft.section_path, f"Table: {' | '.join(headers)}"]
    for row in rows[1:]:
        lines.append(f"{headers[0]}: {row[0].strip()}")
        lines.extend(format_table_field(headers[1], row[1].strip()))
        lines.extend(format_table_field(headers[2], row[2].strip()))
    return [(f"{draft.section_path}{SECTION_SEPARATOR}{headers[0]}", sanitize_chunk_text("\n".join(lines), draft.section_path), {"table_chunking": "small_relational_table", "table_structure_index": str(structure_index)})]


def direct_table_structure_chunks(draft: "ChunkDraft", rows: list[list[str]], structure_index: int) -> TableChunkOutput | None:
    """Apply the ordered table policy, then use the generic column fallback."""
    rows = normalize_table_rows(rows)
    parallel_description = split_two_column_parallel_description(draft, rows, structure_index)
    if parallel_description is not None:
        return parallel_description
    hierarchical_matrix = split_hierarchical_row_matrix(draft, rows, structure_index)
    if hierarchical_matrix is not None:
        return hierarchical_matrix
    early = first_matching_strategy((
        TableStrategy("long_two_column_reference", split_long_two_column_reference_rows),
        TableStrategy("two_column_comparison", split_two_column_comparison),
        TableStrategy("repeated_rate_schedule", split_repeated_rate_schedule_table),
    ), draft, rows, structure_index)
    if early is not None:
        return early
    if len(rows) < 3 or len(rows[0]) < 3:
        return None
    specialized = first_matching_strategy((
        TableStrategy("bundle_partner_columns", split_bundle_partner_columns),
        TableStrategy("generic_offer_rows", split_generic_offer_rows),
        TableStrategy("grouped_three_column_rows", split_grouped_three_column_table),
        TableStrategy("small_relational_table", split_small_relational_table),
        TableStrategy("row_mapping_window", split_row_mapping_table),
        TableStrategy("paired_country_columns", split_paired_country_columns),
    ), draft, rows, structure_index)
    if specialized is not None:
        return specialized
    header_row_index = 0
    if len(rows) > 1 and repeated_value_ratio(rows[0][1:]) < repeated_value_ratio(rows[1][1:]):
        header_row_index = 1
    group_title = table_group_title(rows)
    outputs: TableChunkOutput = []
    for column in range(1, len(rows[header_row_index])):
        header_cells = [group_title] if group_title else []
        for header_index in range(header_row_index + 1):
            if column >= len(rows[header_index]):
                continue
            cell = rows[header_index][column].strip()
            if cell and cell != rows[header_index][0].strip():
                header_cells.append(cell)
        label = build_column_chunk_label(header_cells)
        if not label:
            continue
        lines = [draft.section_path, f"Item: {label}"]
        for row in rows[header_row_index + 1:]:
            if column >= len(row):
                continue
            key, value = row[0].strip(), row[column].strip()
            if key and value:
                lines.extend(format_table_field(key, value))
            elif value:
                lines.append(value)
        if len(lines) > 2:
            outputs.append((f"{draft.section_path}{SECTION_SEPARATOR}{label}", sanitize_chunk_text("\n".join(lines).strip(), draft.section_path), {"table_chunking": "structured_column_group", "table_structure_index": str(structure_index), "table_group": label}))
    return outputs or None
