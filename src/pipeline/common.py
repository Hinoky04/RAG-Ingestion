"""Backward-compatible imports for the original pipeline helper module."""

from src.pipeline.artifacts import load_chunks, save_chunks, save_document, save_markdown
from src.pipeline.parser_factory import parser_for
from src.pipeline.paths import DEFAULT_CHUNK_DIR, DEFAULT_MARKDOWN_DIR, DEFAULT_OUTPUT_DIR, DEFAULT_REGISTRY
from src.pipeline.registry_io import load_registry

__all__ = [
    "DEFAULT_CHUNK_DIR",
    "DEFAULT_MARKDOWN_DIR",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_REGISTRY",
    "load_chunks",
    "load_registry",
    "parser_for",
    "save_chunks",
    "save_document",
    "save_markdown",
]
