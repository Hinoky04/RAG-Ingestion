from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class DocumentStatus(str, Enum):
    """Simple lifecycle states for local ingestion."""

    ACTIVE = "active"
    CHANGED = "changed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class BlockType(str, Enum):
    """Basic content types recovered by parsers."""

    TITLE = "title"
    HEADING = "heading"
    TEXT = "text"
    TABLE = "table"
    LIST_ITEM = "list_item"
    UNKNOWN = "unknown"


class DocumentRecord(BaseModel):
    """Registry entry for one source file before parsing starts."""

    document_id: str = Field(default_factory=lambda: new_id("doc"))
    source_path: str
    file_name: str
    file_type: str
    checksum: str
    client_id: str = "unknown"
    document_type: str = "unknown"
    version: str = "v1"
    access_scope: str = "internal"
    status: DocumentStatus = DocumentStatus.ACTIVE
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @field_validator("source_path")
    @classmethod
    def normalize_source_path(cls, value: str) -> str:
        return str(Path(value))


class ParsedBlock(BaseModel):
    """Smallest useful unit extracted from a document parser."""

    block_id: str = Field(default_factory=lambda: new_id("block"))
    document_id: str
    page_number: int | None = None
    block_type: BlockType = BlockType.TEXT
    text: str
    heading_level: int | None = None
    source_path: str
    parser_name: str
    parser_version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("ParsedBlock.text cannot be empty")
        return cleaned


class CanonicalDocument(BaseModel):
    """Clean, normalized document representation used by later pipeline steps."""

    document_id: str
    client_id: str = "unknown"
    document_type: str = "unknown"
    source_path: str
    file_name: str
    version: str = "v1"
    access_scope: str = "internal"
    blocks: list[ParsedBlock] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class DocumentChunk(BaseModel):
    """Retrieval unit that will be embedded and stored in the vector database."""

    chunk_id: str = Field(default_factory=lambda: new_id("chunk"))
    document_id: str
    client_id: str = "unknown"
    document_type: str = "unknown"
    source_path: str
    file_name: str
    section_path: str = "Unknown Section"
    page_start: int | None = None
    page_end: int | None = None
    text: str
    source_block_ids: list[str] = Field(default_factory=list)
    version: str = "v1"
    access_scope: str = "internal"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def chunk_text_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("DocumentChunk.text cannot be empty")
        return cleaned

    @property
    def citation(self) -> str:
        """Human-readable source pointer for demos and debugging."""

        page = "unknown page"
        if self.page_start is not None and self.page_end is not None:
            page = f"page {self.page_start}" if self.page_start == self.page_end else f"pages {self.page_start}-{self.page_end}"
        return f"{self.file_name}, {page}, {self.section_path}"


class RetrievalResult(BaseModel):
    """Result returned from vector search, including enough metadata to cite it."""

    chunk_id: str
    score: float
    text: str
    document_id: str
    client_id: str = "unknown"
    source_path: str
    file_name: str
    section_path: str = "Unknown Section"
    page_start: int | None = None
    page_end: int | None = None
    version: str = "v1"
    access_scope: str = "internal"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Human-readable source pointer for the retrieved chunk."""

        page = "unknown page"
        if self.page_start is not None and self.page_end is not None:
            page = f"page {self.page_start}" if self.page_start == self.page_end else f"pages {self.page_start}-{self.page_end}"
        return f"{self.file_name}, {page}, {self.section_path}"
