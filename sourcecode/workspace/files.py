"""Safe local-file helpers for the managed workspace directories."""

from __future__ import annotations

import hashlib
from pathlib import Path


def safe_upload_name(file_name: str) -> str:
    safe_name = Path(file_name).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Uploaded file must have a valid filename")
    return safe_name


def safe_delete_file(path_value: str | Path, allowed_roots: list[Path]) -> None:
    """Delete a file only when its resolved path belongs to an allowed root."""

    try:
        resolved = Path(path_value).resolve()
    except OSError:
        return

    allowed = [root.resolve() for root in allowed_roots]
    if not any(root == resolved or root in resolved.parents for root in allowed):
        return

    try:
        resolved.unlink(missing_ok=True)
    except OSError:
        return


def save_uploaded_file(upload_dir: Path, file_name: str, file_bytes: bytes, document_type: str) -> Path:
    """Persist an upload beneath its document type and content checksum."""

    safe_name = safe_upload_name(file_name)
    target_dir = upload_dir / document_type
    target_dir.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(file_bytes).hexdigest()[:12]
    target_path = target_dir / checksum / safe_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(file_bytes)
    return target_path


def read_managed_source(source_path: str | Path, file_name: str, file_type: str, upload_root: Path) -> tuple[str, bytes, str]:
    """Read a download only when it remains within the managed upload tree."""

    path = Path(source_path)
    resolved = path.resolve()
    if upload_root.resolve() not in resolved.parents:
        raise ValueError("Source file is outside the managed upload workspace")

    mime = (
        "application/pdf"
        if file_type == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return file_name, resolved.read_bytes(), mime
