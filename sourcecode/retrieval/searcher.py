"""Search ChromaDB and avoid filling the result list with one repeated section."""

from __future__ import annotations

from pathlib import Path

from sourcecode.indexing.chroma_store import DEFAULT_CHROMA_DIR, ChromaChunkStore
from sourcecode.indexing.embedder import DEFAULT_MODEL_NAME, LocalEmbedder
from sourcecode.representation.schemas import RetrievalResult
from sourcecode.retrieval.ranking import distance_to_score, diversify_results, first_or_none, metadata_filter


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
    # Get extra hits first. After repeated section is removed, top_k is still full.
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
