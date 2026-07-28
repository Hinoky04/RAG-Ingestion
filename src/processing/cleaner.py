from __future__ import annotations

import re
from collections import Counter

from src.representation.schemas import BlockType, CanonicalDocument, ParsedBlock


REPEATED_NOISE_PATTERNS = (
    "synthetic demo data - not real customer data",
    "created only for learning and testing",
    "not an authentic company document",
    "deception, impersonation, or policy representation",
)

MOJIBAKE_REPLACEMENTS = {
    "鈥檚": "'s",
    "鈥檙": "'r",
    "鈥檒": "'l",
    "鈥榮": "'s",
    "鈥渕": '"m',
    "鈥淲": '"W',
    "鈥楴": "'N",
    "鈥?": '"',
    "鈥�": '"',
    "鈥": "'",
}

PAGE_NUMBER_PATTERN = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE)
PDF_PAGE_FOOTER_PATTERN = re.compile(r"^PAGE\s+\d+\s+OF\s+\d+\s+-\s+.+", re.IGNORECASE)

MOJIBAKE_REPLACEMENTS.update(
    {
        "\u9205\u6a88\u6a9a": "'s",
        "\u9205\u6a88\u6a9b": "'t",
        "\u9205\u6a88\u6a99": "'r",
        "\u9205\u6a88\u6a9d": "'v",
        "\u9205\u6a88\u6a92": "'l",
        "\u9205\u6a88\u6a87": "'d",
        "\u9205\u6dd2": '"W',
        "\u9205\u6e15": '"m',
        "\u9205?": '"',
        "\u9205\ufffd": '"',
    }
)


def normalize_text(text: str, preserve_newlines: bool = False) -> str:
    for bad, replacement in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, replacement)

    text = text.replace("\uf0b7", "-")
    if preserve_newlines:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        text = "\n".join(line for line in lines if line)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_repeated_noise(text: str) -> bool:
    lowered = text.lower()
    if lowered in {"representation.", "policy representation."}:
        return True
    if PAGE_NUMBER_PATTERN.match(text) or PDF_PAGE_FOOTER_PATTERN.match(text):
        return True
    return any(pattern in lowered for pattern in REPEATED_NOISE_PATTERNS)


def repeated_headers(blocks: list[ParsedBlock], min_repeats: int = 3) -> set[str]:
    counts = Counter(normalize_text(block.text) for block in blocks)
    return {
        text
        for text, count in counts.items()
        if count >= min_repeats and len(text) <= 140
    }


def clean_document(document: CanonicalDocument) -> CanonicalDocument:
    """Return a cleaned copy of the canonical document.

    This stays conservative on purpose: if a line may contain useful policy text,
    keep it. Bad cleaning is harder to debug than mild noise.
    """

    header_candidates = repeated_headers(document.blocks)
    cleaned_blocks: list[ParsedBlock] = []

    for block in document.blocks:
        text = normalize_text(block.text, preserve_newlines=block.block_type == BlockType.TABLE)
        if not text:
            continue

        if block.metadata.get("repeated_margin_noise"):
            continue

        if is_repeated_noise(text):
            continue

        if text in header_candidates:
            continue

        cleaned_blocks.append(block.model_copy(update={"text": text}))

    metadata = dict(document.metadata)
    metadata.update(
        {
            "cleaner": "conservative_v2",
            "original_block_count": len(document.blocks),
            "cleaned_block_count": len(cleaned_blocks),
            "removed_block_count": len(document.blocks) - len(cleaned_blocks),
        }
    )

    return document.model_copy(update={"blocks": cleaned_blocks, "metadata": metadata})
