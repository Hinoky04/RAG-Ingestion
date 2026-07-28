from __future__ import annotations

from src.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


def block_to_markdown(block: ParsedBlock) -> str:
    if block.block_type == BlockType.HEADING:
        level = block.heading_level or 2
        level = max(1, min(level, 4))
        return f"{'#' * level} {block.text}"

    if block.block_type == BlockType.TABLE:
        return block.text

    if block.block_type == BlockType.LIST_ITEM:
        return f"- {block.text.lstrip('- ').strip()}"

    return block.text


def build_markdown(document: CanonicalDocument) -> str:
    """Build a readable preview. JSON remains the canonical pipeline artifact."""

    lines = [
        f"# {document.file_name}",
        "",
        f"- Document ID: `{document.document_id}`",
        f"- Client: `{document.client_id}`",
        f"- Type: `{document.document_type}`",
        f"- Source: `{document.source_path}`",
        "",
        "---",
        "",
    ]

    previous_page: int | None = None
    for block in document.blocks:
        if block.page_number is not None and block.page_number != previous_page:
            lines.extend(["", f"<!-- Page {block.page_number} -->", ""])
            previous_page = block.page_number

        lines.append(block_to_markdown(block))
        lines.append("")

    return "\n".join(lines).strip() + "\n"
