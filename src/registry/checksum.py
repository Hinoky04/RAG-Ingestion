from __future__ import annotations

import hashlib
from pathlib import Path


def calculate_checksum(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a SHA-256 checksum based on file content, not the file name."""

    file_path = Path(path)
    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)

    return digest.hexdigest()
