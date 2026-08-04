"""Data structures produced while reconstructing PDF page layout."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PDFLine:
    text: str
    page_number: int
    line_number: int
    y0: float
    y1: float
    page_height: float
    max_font_size: float
    avg_font_size: float
    is_bold: bool
    x0: float = 0.0
    x1: float = 0.0
    is_table_grid: bool = False
