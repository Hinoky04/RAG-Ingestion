# PostgreSQL Ingestion Control Schema

## Entity Relationship Diagram

```mermaid
erDiagram
    USERS {
        text user_id PK
        text email
        text display_name
        text role
        timestamptz created_at
    }

    CLIENTS {
        text client_id PK
        text client_name
        text owner_user_id FK
        jsonb metadata_json
        timestamptz created_at
    }

    USER_CLIENT_ACCESS {
        text user_id PK, FK
        text client_id PK, FK
        text permission
        timestamptz created_at
    }

    DOCUMENTS {
        text document_id PK
        text source_path
        text file_name
        text file_type
        text checksum
        text client_id FK
        text document_type
        text version
        text access_scope
        text status
        text parser_name
        text parser_version
        text collection_name
        text error_message
        jsonb metadata_json
        timestamptz created_at
        timestamptz updated_at
        timestamptz indexed_at
    }

    DOCUMENT_VERSIONS {
        bigint version_id PK
        text document_id FK
        text version_label
        text source_hash
        text parser_name
        text parser_version
        text chunking_version
        text status
        boolean is_current
        jsonb metadata_json
        timestamptz created_at
    }

    PROCESSING_RUNS {
        bigint run_id PK
        text document_id FK
        text run_status
        text parser_name
        text parser_version
        jsonb validation_summary
        timestamptz created_at
    }

    ARTIFACTS {
        bigint artifact_id PK
        text document_id FK
        text artifact_type
        text artifact_path
        jsonb artifact_meta
        jsonb artifact_summary
        timestamptz created_at
    }

    CHUNKS {
        text chunk_id PK
        text document_id FK
        int chunk_index
        text section_path
        int page_start
        int page_end
        text text_preview
        jsonb source_block_ids
        jsonb metadata_json
        timestamptz created_at
        timestamptz indexed_at
    }

    VALIDATION_EVENTS {
        bigint event_id PK
        text document_id FK
        bigint run_id FK
        text severity
        text event_code
        text event_message
        jsonb event_meta
        timestamptz created_at
    }

    USERS ||--o{ CLIENTS : owns
    USERS ||--o{ USER_CLIENT_ACCESS : has_access
    CLIENTS ||--o{ USER_CLIENT_ACCESS : grants_access
    CLIENTS ||--o{ DOCUMENTS : owns
    DOCUMENTS ||--o{ DOCUMENT_VERSIONS : has_versions
    DOCUMENTS ||--o{ PROCESSING_RUNS : has_runs
    DOCUMENTS ||--o{ ARTIFACTS : produces
    DOCUMENTS ||--o{ CHUNKS : splits_into
    DOCUMENTS ||--o{ VALIDATION_EVENTS : has_validation_events
    PROCESSING_RUNS ||--o{ VALIDATION_EVENTS : records
```

## Table Comments

| Table | Comment |
| --- | --- |
| `users` | Future application users or operators. |
| `clients` | Client or knowledge-owner scope, for example Daythree or a sample bank. |
| `user_client_access` | Permission mapping between users and client scopes. |
| `documents` | Main registry for uploaded sources and current automation status. |
| `document_versions` | Version history based on document id, version label, and source hash. |
| `processing_runs` | Parser/indexing run log with validation summary JSONB. |
| `artifacts` | Paths and lightweight summaries for generated JSON, Markdown, and chunk files. |
| `chunks` | Chunk-level tracking with `chunk_id`, order, source section, preview, and indexing state. |
| `validation_events` | Automated validation warnings, failures, and parser quality events. |
