from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from sourcecode.representation.schemas import DocumentChunk


DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"
# README downloads the model to this same folder.
DEFAULT_CACHE_DIR = Path(".cache/huggingface")


@dataclass
class LocalEmbedder:
    """Small wrapper around sentence-transformers for local embeddings."""

    model_name: str = DEFAULT_MODEL_NAME
    cache_dir: Path = DEFAULT_CACHE_DIR
    local_files_only: bool = True

    def __post_init__(self) -> None:
        self.model = SentenceTransformer(
            self.model_name,
            cache_folder=str(self.cache_dir),
            local_files_only=self.local_files_only,
        )

    def text_for_embedding(self, chunk: DocumentChunk) -> str:
        return f"Section: {chunk.section_path}\nText: {chunk.text}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors).astype(float).tolist()

    def embed_chunks(self, chunks: list[DocumentChunk]) -> list[list[float]]:
        return self.embed_texts([self.text_for_embedding(chunk) for chunk in chunks])
