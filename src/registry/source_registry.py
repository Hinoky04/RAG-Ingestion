from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from src.registry.checksum import calculate_checksum
from src.representation.schemas import DocumentRecord


DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_OUTPUT = Path("data/processed/registry.json")
DEFAULT_EXTENSIONS = {".pdf", ".docx"}


def path_under_data_raw(path: Path) -> tuple[str, ...]:
    """Return the path parts after data/raw, if the file lives there."""

    parts = path.resolve().parts
    for index in range(len(parts) - 1):
        if parts[index].lower() == "data" and parts[index + 1].lower() == "raw":
            return tuple(parts[index + 2 :])
    return ()


def infer_document_type(path: Path) -> str:
    """Use the second folder under data/raw as a simple document type hint."""

    relative_parts = path_under_data_raw(path)
    if len(relative_parts) > 1:
        return relative_parts[-2]
    return "unknown"


def display_path(path: Path) -> str:
    """Keep registry paths portable instead of storing machine-specific absolute paths."""

    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def find_supported_files(raw_dir: Path, extensions: set[str]) -> list[Path]:
    files = [
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ]
    return sorted(files)


def build_registry(raw_dir: str | Path = DEFAULT_RAW_DIR, extensions: set[str] | None = None) -> list[DocumentRecord]:
    raw_path = Path(raw_dir).resolve()
    selected_extensions = extensions or DEFAULT_EXTENSIONS

    if not raw_path.exists():
        raise FileNotFoundError(f"Raw directory does not exist: {raw_path}")

    records: list[DocumentRecord] = []

    for file_path in find_supported_files(raw_path, selected_extensions):
        # Folder names are not perfect metadata, but they are reliable enough for the current MVP.
        record = DocumentRecord(
            source_path=display_path(file_path),
            file_name=file_path.name,
            file_type=file_path.suffix.lower().lstrip("."),
            checksum=calculate_checksum(file_path),
            document_type=infer_document_type(file_path),
        )
        records.append(record)

    return records


def save_registry(records: list[DocumentRecord], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    adapter = TypeAdapter(list[DocumentRecord])
    payload = adapter.dump_python(records, mode="json")

    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def parse_extensions(values: list[str]) -> set[str]:
    extensions = set()
    for value in values:
        suffix = value.lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        extensions.add(suffix)
    return extensions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a source registry from raw documents.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR), help="Folder to scan for raw documents.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to write the registry JSON.")
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=sorted(DEFAULT_EXTENSIONS),
        help="File extensions to include, for example: pdf docx",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = build_registry(
        raw_dir=args.raw_dir,
        extensions=parse_extensions(args.extensions),
    )
    output = save_registry(records, args.output)

    print(f"Registered {len(records)} document(s)")
    print(f"Wrote registry to {output}")


if __name__ == "__main__":
    main()
