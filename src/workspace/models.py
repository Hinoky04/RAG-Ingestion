from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re


def _slug(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


@dataclass
class WorkspaceDocument:
    document_id: str
    source_path: str
    file_name: str
    file_type: str
    checksum: str
    document_type: str
    version: str
    status: str
    parser_name: str | None
    parser_version: str | None
    collection_name: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def display_id(self) -> str:
        # Keep the database id untouched, but expose a label that is easier to
        # discuss during review and screenshots.
        stem = _slug(self.file_name.rsplit(".", 1)[0])[:36]
        doc_type = _slug(self.document_type)[:16]
        suffix = self.document_id.split("_")[-1][-4:]
        return f"doc_{doc_type}_{stem}_{suffix}"
