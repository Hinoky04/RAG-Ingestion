from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
