"""Serialization boundary for canonical document registries."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from src.representation.schemas import DocumentRecord


def load_registry(registry_path: str | Path) -> list[DocumentRecord]:
    path = Path(registry_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(list[DocumentRecord]).validate_python(payload)
