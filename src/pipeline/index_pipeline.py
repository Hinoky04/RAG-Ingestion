from __future__ import annotations

import argparse
from pathlib import Path

from src.indexing.chroma_store import ChromaChunkStore, DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAME
from src.indexing.embedder import DEFAULT_MODEL_NAME, LocalEmbedder
from src.pipeline.artifacts import load_chunks
from src.pipeline.index_service import index_document_chunks
from src.pipeline.paths import DEFAULT_CHUNK_DIR


def load_chunk_dir(chunk_dir: str | Path) -> list[DocumentChunk]:
    directory = Path(chunk_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Chunk directory does not exist: {directory}")

    chunks: list[DocumentChunk] = []
    for file_path in sorted(directory.glob("*.json")):
        chunks.extend(load_chunks(file_path))

    return chunks


def index_chunks(
    chunk_dir: str | Path,
    collection_name: str,
    persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    model_name: str = DEFAULT_MODEL_NAME,
    reset_collection: bool = False,
) -> int:
    chunks = load_chunk_dir(chunk_dir)
    if not chunks:
        print(f"No chunks found in {chunk_dir}")
        return 0

    indexed_count = index_document_chunks(
        chunks=chunks,
        collection_name=collection_name,
        persist_dir=persist_dir,
        model_name=model_name,
        reset_collection=reset_collection,
    )
    store = ChromaChunkStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
        reset_collection=False,
    )

    print(f"Indexed {indexed_count} chunk(s)")
    print(f"Collection: {collection_name}")
    print(f"Collection count: {store.count()}")
    print(f"Chroma path: {persist_dir}")

    return indexed_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed chunks and store them in ChromaDB.")
    parser.add_argument("--chunk-dir", default=str(DEFAULT_CHUNK_DIR), help="Folder containing chunk JSON files.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME, help="ChromaDB collection name.")
    parser.add_argument("--persist-dir", default=str(DEFAULT_CHROMA_DIR), help="ChromaDB persistence folder.")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="sentence-transformers model name.")
    parser.add_argument("--reset-collection", action="store_true", help="Delete the collection before indexing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index_chunks(
        chunk_dir=args.chunk_dir,
        collection_name=args.collection,
        persist_dir=args.persist_dir,
        model_name=args.model,
        reset_collection=args.reset_collection,
    )


if __name__ == "__main__":
    main()
