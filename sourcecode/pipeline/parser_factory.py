"""Parser selection for supported source formats."""

from __future__ import annotations

from sourcecode.parsers.base_parser import BaseParser
from sourcecode.parsers.docx_parser import DOCXParser
from sourcecode.parsers.pdf_parser import PDFParser
from sourcecode.representation.schemas import DocumentRecord


def parser_for(record: DocumentRecord) -> BaseParser | None:
    if record.file_type.lower() == "pdf":
        return PDFParser()
    if record.file_type.lower() == "docx":
        return DOCXParser()
    return None
