"""Default local paths used by the batch ingestion pipeline."""

from __future__ import annotations

from pathlib import Path


DEFAULT_REGISTRY = Path("data/processed/registry.json")
DEFAULT_OUTPUT_DIR = Path("data/processed/documents")
DEFAULT_MARKDOWN_DIR = Path("data/processed/markdown")
DEFAULT_CHUNK_DIR = Path("data/processed/chunks")
