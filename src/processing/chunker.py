from __future__ import annotations

from dataclasses import dataclass, field

from src.representation.schemas import BlockType, CanonicalDocument, DocumentChunk, ParsedBlock


MIN_HEADINGS_FOR_STRUCTURE = 3
MAX_WORDS = 350
OVERLAP_WORDS = 50
MIN_CHUNK_WORDS = 25


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


def blocks_to_chunk(
    document: CanonicalDocument,
    section_path: str,
    blocks: list[ParsedBlock],
    text: str,
    split_index: int | None = None,
) -> DocumentChunk:
    page_start, page_end = pages_for(blocks)
    chunk_section = section_path if split_index is None else f"{section_path} (part {split_index + 1})"

    return DocumentChunk(
        document_id=document.document_id,
        client_id=document.client_id,
        document_type=document.document_type,
        source_path=document.source_path,
        file_name=document.file_name,
        section_path=chunk_section,
        page_start=page_start,
        page_end=page_end,
        text=text,
        source_block_ids=[block.block_id for block in blocks],
        version=document.version,
        access_scope=document.access_scope,
        metadata={
            "chunker": "defensive_v1",
            "block_count": len(blocks),
        },
    )


def chunk_document(document: CanonicalDocument) -> list[DocumentChunk]:
    """Create chunks using structure first, then safer fallbacks.

    This is intentionally defensive: clean SOPs should benefit from headings,
    while messy public PDFs still produce usable page/length chunks.
    """

    if heading_count(document) >= MIN_HEADINGS_FOR_STRUCTURE:
        drafts = group_web_by_major_heading(document) if document.document_type == "web" else group_by_heading(document)
    else:
        drafts = group_by_page(document)
    drafts = merge_tiny_drafts(drafts)
    chunks: list[DocumentChunk] = []

    for draft in drafts:
        text = draft_text(draft.blocks)
        if not text:
            continue

        split_texts = split_words(text)
        for index, split_text in enumerate(split_texts):
            split_index = index if len(split_texts) > 1 else None
            chunks.append(blocks_to_chunk(document, draft.section_path, draft.blocks, split_text, split_index))

    return chunks
