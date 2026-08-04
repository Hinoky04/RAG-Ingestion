"""Chunk text-based PDFs while retaining section and table context."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.representation.schemas import BlockType, CanonicalDocument, DocumentChunk, ParsedBlock


PDF_TARGET_WORDS = 260
PDF_MIN_WORDS = 40
OPEN_PHRASE_ENDINGS = frozenset({
    "at", "by", "for", "from", "in", "into", "of", "on", "or", "to", "with",
})
TABLE_RECORD_IDENTITY_FIELDS = frozenset({
    # These identify an individual table record, unlike generic field labels
    # such as Plan or Offer which are commonly column headers.
    "bundle", "package",
})
ELIGIBILITY_MARKERS = frozenset({"✅", "✖", "✖️", "🔵"})


@dataclass
class PDFSection:
    title: str
    blocks: list[ParsedBlock] = field(default_factory=list)


def words(text: str) -> int:
    return len(text.split())


def text_for(blocks: list[ParsedBlock]) -> str:
    return "\n".join(block.text for block in blocks if block.text.strip()).strip()


def major_sections(document: CanonicalDocument) -> list[PDFSection]:
    """Group PDF blocks by reliable level-one headings without discarding preamble."""
    sections = [PDFSection("Introduction")]
    for block in document.blocks:
        if block.block_type == BlockType.HEADING and block.heading_level == 1:
            sections.append(PDFSection(block.text, [block]))
        else:
            sections[-1].blocks.append(block)

    # A title-only preamble is useful context but is not a useful retrieval unit.
    # Attach it to the first real section while retaining both its text and order.
    if len(sections) > 1 and words(text_for(sections[0].blocks)) < PDF_MIN_WORDS:
        sections[1].blocks = sections[0].blocks + sections[1].blocks
        sections = sections[1:]

    # A level-one label with no source body is a navigation marker, not
    # retrievable evidence.  Do not make it a title-only chunk and, crucially,
    # do not attach it to the next section (which changes the relationship).
    return [section for section in sections if section_has_body(section)]


def section_has_body(section: PDFSection) -> bool:
    return any(
        not (
            block.block_type == BlockType.HEADING
            and block.heading_level == 1
            and block.text == section.title
        )
        for block in section.blocks
    )


def section_units(section: PDFSection) -> list[list[ParsedBlock]]:
    """Keep a table with its immediately preceding explanation when possible."""
    units: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    for block in section.blocks:
        is_subheading = (
            block.block_type == BlockType.HEADING
            and block.heading_level is not None
            and block.heading_level > 1
        )
        # A positioned PDF label can be classified as a short heading even
        # though it completes the preceding list/table row (for example,
        # "services are not available in" followed by "Thailand"). Keep that
        # relationship atomic so packing never splits the subject from its
        # condition.
        if is_subheading and current and not follows_open_phrase(current[-1]):
            units.append(current)
            current = []
        current.append(block)
        if block.block_type == BlockType.TABLE:
            units.append(current)
            current = []
    if current:
        units.append(current)
    return units


def follows_open_phrase(block: ParsedBlock) -> bool:
    """Whether the next positioned label completes this source row."""
    if block.block_type not in {BlockType.TEXT, BlockType.LIST_ITEM, BlockType.TABLE}:
        return False
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if not lines:
        return False
    tail = lines[-1].rstrip()
    if tail.endswith((".", "!", "?", ":", ";")):
        return False
    tokens = tail.lower().split()
    return bool(tokens and tokens[-1].rstrip(",") in OPEN_PHRASE_ENDINGS)


def table_pieces(block: ParsedBlock, budget: int) -> list[list[ParsedBlock]]:
    """Split an oversized extracted table only between rows, repeating its header."""
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if len(lines) < 2:
        return [[block]]
    header_context = stable_table_header_context(lines)
    pieces: list[str] = []
    current: list[str] = []
    for line in lines:
        candidate = "\n".join([*current, line])
        if current and words(candidate) > budget:
            pieces.append("\n".join(current))
            # A continuation must carry the source table's real header, not
            # merely its first layout row. Some PDFs place feature rows before
            # a later multi-level record header.
            current = [*header_context, line] if header_context else [line]
        else:
            current.append(line)
    if current:
        pieces.append("\n".join(current))
    return [
        [block.model_copy(update={"text": piece, "metadata": {**block.metadata, "pdf_table_piece": index}})]
        for index, piece in enumerate(pieces)
    ]


def is_numbered_table_record(line: str) -> bool:
    """Whether a pipe row starts with a visible numeric record identifier."""
    cells = [cell.strip() for cell in line.lstrip("| ").split("|")]
    return bool(cells and cells[0].isdigit())


def is_eligibility_matrix_record(line: str) -> bool:
    """Whether a row has enough explicit status cells to continue a matrix."""
    cells = [cell.strip() for cell in line.lstrip("| ").split("|")]
    return len(cells) >= 5 and sum(cell in ELIGIBILITY_MARKERS for cell in cells[1:]) >= 3


def stable_table_header_context(lines: list[str]) -> list[str]:
    """Return the short, source-faithful header cluster before numeric records.

    A large grid can contain introductory feature rows before its actual record
    labels.  Preserve only the final three pre-record lines, which covers a
    title, a grouped header, and its field header without copying the whole
    preceding table into every continuation.
    """
    first_record = next((index for index, line in enumerate(lines) if is_numbered_table_record(line)), None)
    if first_record is None:
        header_terms = {"category", "price", "quota", "validity", "plan", "offer", "eligibility"}
        for line in reversed(lines):
            labels = {cell.strip().casefold() for cell in line.split("|") if cell.strip()}
            if len(labels & header_terms) >= 2:
                return [line]
        return [lines[0]] if "|" in lines[0] else []

    candidates = lines[max(0, first_record - 3):first_record]
    if not candidates:
        return []
    last = candidates[-1]
    nonempty_cells = [cell.strip() for cell in last.split("|") if cell.strip()]
    # The final header line needs multiple textual fields. This rejects a
    # preceding prose line or a normal data row as continuation context.
    if "|" not in last or len(nonempty_cells) < 2 or any(cell.isdigit() for cell in nonempty_cells):
        return []
    return candidates


def trailing_table_header(unit: list[ParsedBlock]) -> list[str] | None:
    """Return a stable source header from the most recent table unit, if any."""
    table = next((block for block in reversed(unit) if block.block_type == BlockType.TABLE), None)
    if table is None:
        return None
    lines = [line.strip() for line in table.text.splitlines() if line.strip()]
    if not lines:
        return None
    return stable_table_header_context(lines) or None


def starts_unlabelled_table_continuation(unit: list[ParsedBlock]) -> bool:
    first = next((block for block in unit if block.text.strip()), None)
    if first is None or first.block_type != BlockType.TABLE:
        return False
    lines = [line.strip() for line in first.text.splitlines() if line.strip()]
    if not lines:
        return False
    line = lines[0]
    # A multi-page eligibility matrix may begin the following page with a
    # category label (for example, ``Prepaid``) before its first symbol row.
    follows_category_label = len(lines) > 1 and is_eligibility_matrix_record(lines[1])
    return (
        line.startswith("|")
        or is_numbered_table_record(line)
        or is_eligibility_matrix_record(line)
        or follows_category_label
    )


def repeat_continuation_table_headers(units: list[list[ParsedBlock]]) -> list[list[ParsedBlock]]:
    """Carry a known header into the immediately following table continuation."""
    repeated: list[list[ParsedBlock]] = []
    for unit in units:
        if repeated and starts_unlabelled_table_continuation(unit):
            header = trailing_table_header(repeated[-1])
            if header:
                first = unit[0]
                header_text = "\n".join(header)
                unit = [
                    first.model_copy(
                        update={
                            "text": f"{header_text}\n{first.text}",
                            "metadata": {**first.metadata, "pdf_repeated_table_header": True},
                        }
                    ),
                    *unit[1:],
                ]
        repeated.append(unit)
    return repeated


def expanded_units(section: PDFSection) -> list[list[ParsedBlock]]:
    units: list[list[ParsedBlock]] = []
    for unit in repeat_continuation_table_headers(section_units(section)):
        table = unit[-1] if unit and unit[-1].block_type == BlockType.TABLE else None
        if table is None or words(table.text) <= PDF_TARGET_WORDS:
            units.append(unit)
            continue

        pieces = table_pieces(table, PDF_TARGET_WORDS - 30)
        units.append([*unit[:-1], *pieces[0]])
        units.extend(pieces[1:])
    return units


def render(section: PDFSection, blocks: list[ParsedBlock]) -> str:
    """Repeat the major section heading while avoiding a duplicate first heading."""
    body_blocks = list(blocks)
    for index, block in enumerate(body_blocks):
        if block.block_type == BlockType.HEADING and block.text == section.title:
            body_blocks.pop(index)
            break
    body = text_for(body_blocks)
    if not body:
        return ""
    if body == section.title or body.startswith(f"{section.title}\n"):
        return body
    return f"{section.title}\n{body}"


def table_field(line: str) -> str:
    """Return the left-most field of a pipe-delimited table row."""
    return line.lstrip("| ").split("|", 1)[0].strip().casefold()


def first_table_row(blocks: list[ParsedBlock]) -> str | None:
    """Return the first source row when a pack begins with a table."""
    first = next((block for block in blocks if block.text.strip()), None)
    if first is None or first.block_type != BlockType.TABLE:
        return None
    return next((line.strip() for line in first.text.splitlines() if line.strip()), None)


def trailing_record_identity(blocks: list[ParsedBlock]) -> tuple[ParsedBlock, str] | None:
    """Find the most recent high-confidence record identity in a table pack."""
    for block in reversed(blocks):
        if block.block_type != BlockType.TABLE:
            continue
        for line in reversed([line.strip() for line in block.text.splitlines() if line.strip()]):
            if table_field(line) in TABLE_RECORD_IDENTITY_FIELDS:
                return block, line
    return None


def repeat_table_record_context(packs: list[list[ParsedBlock]]) -> list[list[ParsedBlock]]:
    """Give a table continuation its preceding record identity when unambiguous.

    The copied row is source-faithful provenance, rather than an inferred value:
    it is added only when a new pack starts directly with a table field such as
    ``Access`` and the prior pack ends with a recognised identity row such as
    ``Bundle | Sports Bundle``.
    """
    contextualized: list[list[ParsedBlock]] = []
    for pack in packs:
        first_row = first_table_row(pack)
        identity = trailing_record_identity(contextualized[-1]) if contextualized else None
        if (
            first_row
            and table_field(first_row) not in TABLE_RECORD_IDENTITY_FIELDS
            and identity is not None
        ):
            source_block, identity_row = identity
            context_block = source_block.model_copy(
                update={
                    "text": identity_row,
                    "metadata": {
                        **source_block.metadata,
                        "pdf_repeated_table_record_context": True,
                    },
                }
            )
            pack = [context_block, *pack]
        contextualized.append(pack)
    return contextualized


def pack_section(section: PDFSection) -> list[list[ParsedBlock]]:
    packs: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    for unit in expanded_units(section):
        candidate = current + unit
        if current and words(render(section, candidate)) > PDF_TARGET_WORDS:
            packs.append(current)
            current = unit
        else:
            current = candidate
    if current:
        packs.append(current)

    # A short tail is more useful attached to its preceding context than alone.
    if len(packs) > 1 and words(render(section, packs[-1])) < PDF_MIN_WORDS:
        packs[-2].extend(packs.pop())
    return repeat_table_record_context(packs)


def chunk_pdf_document(document: CanonicalDocument) -> list[DocumentChunk]:
    """Create retrieval chunks that preserve PDF section and table context."""
    # Imported lazily to keep the generic chunker free of a PDF-only dependency.
    from src.processing.chunker import blocks_to_chunk

    chunks: list[DocumentChunk] = []
    for section in major_sections(document):
        packs = pack_section(section)
        for index, pack in enumerate(packs):
            text = render(section, pack)
            if not text:
                continue
            chunks.append(
                blocks_to_chunk(
                    document,
                    section.title,
                    pack,
                    text,
                    split_index=index if len(packs) > 1 else None,
                    metadata={
                        "chunking_strategy": "pdf_context_first_v1",
                        "pdf_section": section.title,
                        "contains_table": str(any(block.block_type == BlockType.TABLE for block in pack)).lower(),
                    },
                )
            )
    return chunks
