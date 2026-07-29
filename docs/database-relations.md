# Database Relations

This is the PostgreSQL control-plane entity relationship view for the `rag_ingestion` schema.

```mermaid
erDiagram
    documents {
        TEXT document_id PK
        TEXT source_path UK
        TEXT file_name
        TEXT file_type
        TEXT checksum
        TEXT document_type
        TEXT version
        TEXT status
        TEXT parser_name
        TEXT parser_version
        TEXT collection_name
        TEXT error_message
        JSONB metadata_json
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
        TIMESTAMPTZ indexed_at
    }

    document_versions {
        BIGSERIAL version_id PK
        TEXT document_id FK
        TEXT version_label
        TEXT source_hash
        TEXT parser_name
        TEXT parser_version
        TEXT status
        BOOLEAN is_current
        JSONB metadata_json
        TIMESTAMPTZ created_at
    }

    artifacts {
        BIGSERIAL artifact_id PK
        TEXT document_id FK
        TEXT artifact_type
        TEXT artifact_path
        JSONB artifact_meta
        JSONB artifact_summary
        TIMESTAMPTZ created_at
    }

    chunks {
        TEXT chunk_id PK
        TEXT document_id FK
        INTEGER chunk_index
        TEXT section_path
        INTEGER page_start
        INTEGER page_end
        TEXT text_preview
        JSONB source_block_ids
        JSONB metadata_json
        TIMESTAMPTZ created_at
        TIMESTAMPTZ indexed_at
    }

    processing_runs {
        BIGSERIAL run_id PK
        TEXT document_id FK
        TEXT run_status
        TEXT parser_name
        TEXT parser_version
        JSONB validation_summary
        TIMESTAMPTZ created_at
    }

    validation_events {
        BIGSERIAL event_id PK
        TEXT document_id FK
        BIGINT run_id FK
        TEXT severity
        TEXT event_code
        TEXT event_message
        JSONB event_meta
        TIMESTAMPTZ created_at
    }

    documents ||--o{ document_versions : has_versions
    documents ||--o{ artifacts : has_artifacts
    documents ||--o{ chunks : has_chunks
    documents ||--o{ processing_runs : has_runs
    documents ||--o{ validation_events : has_events
    processing_runs ||--o{ validation_events : emits
```

## Core design

- `documents` is the parent record for one registered source document in the workspace.
- `document_versions` stores version history and checksum-backed version rows for that document.
- `artifacts` stores traceable output file paths such as canonical JSON, markdown preview, and chunk artifact files.
- `chunks` stores lightweight retrieval metadata for each validated chunk.
- `processing_runs` stores ingestion and indexing run history.
- `validation_events` stores deterministic validation warnings and errors, optionally linked to a specific run.

## Key relational rules

- `document_versions.document_id -> documents.document_id` with `ON DELETE CASCADE`
- `artifacts.document_id -> documents.document_id` with `ON DELETE CASCADE`
- `chunks.document_id -> documents.document_id` with `ON DELETE CASCADE`
- `processing_runs.document_id -> documents.document_id` with `ON DELETE CASCADE`
- `validation_events.document_id -> documents.document_id` with `ON DELETE CASCADE`
- `validation_events.run_id -> processing_runs.run_id` with `ON DELETE SET NULL`

## Why this matters

This schema makes PostgreSQL the only control-plane source of truth for:

- upload registration
- duplicate handling
- version history
- artifact traceability
- validated chunk metadata
- run history
- validation status

ChromaDB remains only the vector store for approved chunks.
