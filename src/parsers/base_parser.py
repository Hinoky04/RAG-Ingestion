from __future__ import annotations

from abc import ABC, abstractmethod

from src.representation.schemas import CanonicalDocument, DocumentRecord


class BaseParser(ABC):
    """Common shape for document parsers used by the ingestion pipeline."""

    parser_name: str
    parser_version: str = "v1"

    @abstractmethod
    def parse(self, record: DocumentRecord) -> CanonicalDocument:
        """Parse one registered source document into canonical blocks."""
