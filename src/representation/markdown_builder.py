from __future__ import annotations

from src.representation.schemas import BlockType, CanonicalDocument, DocumentChunk, ParsedBlock


def block_to_markdown(block: ParsedBlock) -> str:
    if block.block_type == BlockType.HEADING:
        level = block.heading_level or 2
        level = max(1, min(level, 4))
        return f"{'#' * level} {block.text}"

    if block.block_type == BlockType.TABLE:
        # Tables may contain merged or nested DOCX cells. Preserve each parsed
        # row verbatim rather than letting Markdown collapse it into a paragraph.
        return f"```text\n{block.text}\n```"

    if block.block_type == BlockType.LIST_ITEM:
        return f"- {block.text.lstrip('- ').strip()}"

    return block.text


def build_markdown(document: CanonicalDocument) -> str:
    """Build a readable preview. JSON remains the canonical pipeline artifact."""

    lines = [
        f"# {document.file_name}",
        "",
        f"- Document ID: `{document.document_id}`",
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


def build_chunk_markdown(document: CanonicalDocument, chunks: list[DocumentChunk]) -> str:
    """Build the review artifact from the finalized evidence sent to indexing."""
    lines = [
        f"# {document.file_name}", "", f"- Document ID: `{document.document_id}`",
        f"- Type: `{document.document_type}`", f"- Source: `{document.source_path}`",
        f"- Validated chunks: `{len(chunks)}`", "", "---", "", "## Validated evidence chunks",
    ]
    for index, chunk in enumerate(chunks, start=1):
        lines.extend(["", f"### Chunk {index:02d} — {chunk.section_path}", "", "```text", chunk.text, "```"])
    return "\n".join(lines).strip() + "\n"
