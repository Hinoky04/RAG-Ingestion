# Architecture

This is a local-first ingestion control plane, not a chatbot application.

```text
PDF / DOCX
  -> parser
  -> canonical document JSON
  -> cleaning and chunking
  -> PostgreSQL state, versions, artifacts, chunks, and validation events
  -> ChromaDB vectors
  -> retrieval result with file, section, and page citation
```

## Storage Responsibilities

PostgreSQL is the system of record for document lifecycle state. It stores the document identity, checksum-based versions, artifact paths, lightweight chunk metadata, and processing history.

Generated canonical JSON, Markdown previews, and full chunk text remain under `data/processed/`. ChromaDB stores embeddings and the metadata needed to cite a result. On re-index, vectors belonging to the document are removed before the current chunks are inserted.

The schema is in [`db/schema.sql`](../db/schema.sql). The six tables are deliberately small:

- `documents`: current source and lifecycle state
- `document_versions`: checksum-based history
- `artifacts`: generated file paths and summaries
- `chunks`: chunk trace metadata
- `processing_runs`: ingestion and indexing history
- `validation_events`: deterministic warnings and failures

## Validation Boundary

Validation confirms that parsing produced blocks, chunks, and expected artifacts. It does not claim that a source document is factually correct or that retrieval quality is production-grade. Retrieval evaluation is keyword-based and must be configured from the local dataset being tested.

## Database Relation Graph

See [`docs/database-relations.md`](./database-relations.md) for the PostgreSQL control-plane ER view, including primary keys, foreign keys, and cascade behavior.
