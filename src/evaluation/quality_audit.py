"""Read-only corpus audit for parser and chunking regressions."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from src.pipeline.common import parser_for
from src.processing.chunker import chunk_document
from src.processing.cleaner import clean_document
from src.processing.quality import assess_chunks, normalized_text
from src.registry.source_registry import DEFAULT_RAW_DIR, build_registry


@dataclass(frozen=True)
class CorpusQualityReport:
    documents: int
    chunks: int
    by_format: dict[str, int]
    short_chunks: int
    duplicate_chunks_within_document: int
    duplicate_chunks_across_documents: int
    chunks_without_locator: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_corpus(raw_dir: str | Path = DEFAULT_RAW_DIR) -> CorpusQualityReport:
    # Workspace uploads are managed copies of source files, not part of the
    # reference corpus used to compare parser/chunker quality.
    records = [
        record for record in build_registry(raw_dir)
        if "workspace_uploads" not in {part.casefold() for part in Path(record.source_path).parts}
    ]
    all_chunks = []
    reports = []
    formats = Counter(record.file_type for record in records)
    for record in records:
        selected_parser = parser_for(record)
        if selected_parser is None:
            continue
        chunks = chunk_document(clean_document(selected_parser.parse(record)))
        all_chunks.extend(chunks)
        reports.append(assess_chunks(chunks))
    across_texts = Counter(normalized_text(chunk.text) for chunk in all_chunks)
    return CorpusQualityReport(
        documents=len(records), chunks=len(all_chunks), by_format=dict(sorted(formats.items())),
        short_chunks=sum(report.short_chunks for report in reports),
        duplicate_chunks_within_document=sum(report.duplicate_chunks for report in reports),
        duplicate_chunks_across_documents=sum(count - 1 for count in across_texts.values() if count > 1),
        chunks_without_locator=sum(report.chunks_without_locator for report in reports),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a read-only parser/chunker quality audit.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_corpus(args.raw_dir)
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
