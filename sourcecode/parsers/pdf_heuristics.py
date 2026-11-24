"""Stateless text heuristics shared by the PDF parser classification rules."""

from __future__ import annotations

import re


def looks_like_transfer_code(line: str) -> bool:
    if not re.search(r"\b\d{3,}\b", line):
        return False
    words = [word for word in re.split(r"\W+", line) if word]
    return len(words) <= 4


def looks_like_numeric_table_label(line: str) -> bool:
    return bool(re.match(r"^\d+\s+[A-Za-z][A-Za-z0-9/&()\-+ ]*$", line))


def looks_like_numbered_sentence(line: str) -> bool:
    return bool(re.match(r"^\d+\.\s+\S+", line)) and len(line.split()) > 5


def looks_like_table_row(line: str) -> bool:
    if "\t" in line or "|" in line:
        return True
    spaced_columns = re.search(r"\S\s{2,}\S", line)
    has_multiple_numbers = len(re.findall(r"\b\d+[\d.,%]*\b", line)) >= 2
    return bool(spaced_columns and has_multiple_numbers)


def looks_like_list_item(line: str) -> bool:
    return bool(re.match(r"^(?:[-•\uf0b7]|\d+\.)\s+\S+", line))
