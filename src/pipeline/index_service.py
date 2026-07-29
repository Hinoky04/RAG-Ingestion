from __future__ import annotations

from pathlib import Path

from src.indexing.chroma_store import DEFAULT_CHROMA_DIR, ChromaChunkStore
from src.indexing.embedder import DEFAULT_MODEL_NAME, LocalEmbedder
from src.representation.schemas import DocumentChunk


def index_document_chunks(
    chunks: list[DocumentChunk],
    collection_name: str,
    persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    model_name: str = DEFAULT_MODEL_NAME,
    reset_collection: bool = False,
) -> int:
    if not chunks:
        return 0

    embedder = LocalEmbedder(model_name=model_name)
    embeddings = embedder.embed_chunks(chunks)
    store = ChromaChunkStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
        reset_collection=reset_collection,
    )
    # Chunk IDs change after a re-parse. Remove prior vectors so retrieval
    # cannot return stale text from an older document version.
    for document_id in {chunk.document_id for chunk in chunks}:
        store.delete_document_chunks(document_id)
    return store.upsert_chunks(chunks, embeddings, model_name=model_name)
