from __future__ import annotations

from pathlib import Path

from sourcecode.registry.checksum import calculate_checksum
from sourcecode.representation.schemas import DocumentRecord


DEFAULT_RAW_DIR = Path("data/raw")
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
    """Find source documents while ignoring Office's transient lock files."""

    files = [
        path
        for path in raw_dir.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() in extensions
            and not path.name.startswith("~$")
        )
    ]
    return sorted(files)


def build_registry(raw_dir: str | Path = DEFAULT_RAW_DIR, extensions: set[str] | None = None) -> list[DocumentRecord]:
    raw_path = Path(raw_dir).resolve()
    selected_extensions = extensions or DEFAULT_EXTENSIONS

    if not raw_path.exists():
        raise FileNotFoundError(f"Raw directory does not exist: {raw_path}")

    records: list[DocumentRecord] = []

    for file_path in find_supported_files(raw_path, selected_extensions):
        # If type is missing, folder name is the only type information here.
        record = DocumentRecord(
            source_path=display_path(file_path),
            file_name=file_path.name,
            file_type=file_path.suffix.lower().lstrip("."),
            checksum=calculate_checksum(file_path),
            document_type=infer_document_type(file_path),
        )
        records.append(record)

    return records
