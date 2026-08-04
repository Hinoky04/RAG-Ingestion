from __future__ import annotations

import argparse
from pathlib import Path
from src.pipeline.paths import (
    DEFAULT_CHUNK_DIR,
    DEFAULT_MARKDOWN_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REGISTRY,
)
from src.pipeline.registry_io import (
    load_registry,
)
from src.pipeline.ingest_service import ingest_record


def ingest_documents(
    registry_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    markdown_dir: str | Path | None = DEFAULT_MARKDOWN_DIR,
    chunk_dir: str | Path | None = DEFAULT_CHUNK_DIR,
) -> list[Path]:
    records = load_registry(registry_path)
    written_files: list[Path] = []

    for record in records:
        try:
            outcome = ingest_record(
                record=record,
                output_dir=output_dir,
                markdown_dir=markdown_dir,
                chunk_dir=chunk_dir,
            )
        except ValueError as exc:
            print(f"Skipping {record.file_name}: {exc}")
            continue

        written_files.append(outcome.artifacts.document_path)
        print(f"Parsed {record.file_name} -> {outcome.artifacts.document_path}")

        if outcome.artifacts.markdown_path is not None:
            print(f"Wrote Markdown preview -> {outcome.artifacts.markdown_path}")

        if outcome.artifacts.chunk_path is not None:
            print(f"Wrote {len(outcome.chunks)} chunk(s) -> {outcome.artifacts.chunk_path}")

    return written_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse registered documents into canonical JSON.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Path to registry JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Folder for parsed document JSON.")
    parser.add_argument("--markdown-dir", default=str(DEFAULT_MARKDOWN_DIR), help="Folder for Markdown previews.")
    parser.add_argument("--chunk-dir", default=str(DEFAULT_CHUNK_DIR), help="Folder for chunk JSON output.")
    parser.add_argument("--no-markdown", action="store_true", help="Skip Markdown preview output.")
    parser.add_argument("--no-chunks", action="store_true", help="Skip chunk output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markdown_dir = None if args.no_markdown else args.markdown_dir
    chunk_dir = None if args.no_chunks else args.chunk_dir
    written_files = ingest_documents(args.registry, args.output_dir, markdown_dir, chunk_dir)
    print(f"Wrote {len(written_files)} canonical document(s)")


if __name__ == "__main__":
    main()
