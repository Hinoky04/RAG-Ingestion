from __future__ import annotations

import argparse
import logging
import textwrap
from pathlib import Path

from src.indexing.chroma_store import DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAME, ChromaChunkStore
from src.indexing.embedder import DEFAULT_MODEL_NAME, LocalEmbedder
from src.representation.schemas import RetrievalResult
from src.retrieval.ranking import distance_to_score, diversify_results, first_or_none, metadata_filter


WRAP_WIDTH = 110


def quiet_noisy_loggers() -> None:
    logging.getLogger("chromadb").setLevel(logging.CRITICAL)
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def search(
    query: str,
    collection_name: str,
    persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    model_name: str = DEFAULT_MODEL_NAME,
    top_k: int = 5,
    document_type: str | None = None,
) -> list[RetrievalResult]:
    embedder = LocalEmbedder(model_name=model_name)
    query_embedding = embedder.embed_texts([query])[0]

    store = ChromaChunkStore(persist_dir=persist_dir, collection_name=collection_name)
    results = store.collection.query(
        query_embeddings=[query_embedding],
        n_results=max(top_k * 3, top_k),
        where=metadata_filter(document_type=document_type),
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]

    output: list[RetrievalResult] = []
    for index, chunk_id in enumerate(ids):
        metadata = first_or_none(metadatas, index) or {}
        text = first_or_none(documents, index) or ""
        distance = first_or_none(distances, index)

        output.append(
            RetrievalResult(
                chunk_id=chunk_id,
                score=distance_to_score(distance),
                text=text,
                document_id=str(metadata.get("document_id", "unknown")),
                source_path=str(metadata.get("source_path", "")),
                file_name=str(metadata.get("file_name", "")),
                section_path=str(metadata.get("section_path", "Unknown Section")),
                page_start=metadata.get("page_start"),
                page_end=metadata.get("page_end"),
                version=str(metadata.get("version", "v1")),
                metadata=dict(metadata),
            )
        )

    return diversify_results(output, top_k)


def print_results(results: list[RetrievalResult]) -> None:
    if not results:
        print("No results found.")
        return

    for index, result in enumerate(results, start=1):
        print(f"\nResult {index}")
        print(f"Score: {result.score:.4f}")
        print(f"Source: {result.file_name}")
        print(f"Citation: {result.citation}")
        print(f"Section: {result.section_path}")
        print("Text:")
        print(textwrap.fill(result.text, width=WRAP_WIDTH))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search indexed chunks with citation metadata.")
    parser.add_argument("query", help="Natural-language query.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME, help="ChromaDB collection name.")
    parser.add_argument("--persist-dir", default=str(DEFAULT_CHROMA_DIR), help="ChromaDB persistence folder.")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="sentence-transformers model name.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return.")
    parser.add_argument("--document-type", default=None, help="Optional document_type filter.")
    return parser.parse_args()


def main() -> None:
    quiet_noisy_loggers()
    args = parse_args()
    results = search(
        query=args.query,
        collection_name=args.collection,
        persist_dir=args.persist_dir,
        model_name=args.model,
        top_k=args.top_k,
        document_type=args.document_type,
    )
    print_results(results)


if __name__ == "__main__":
    main()
