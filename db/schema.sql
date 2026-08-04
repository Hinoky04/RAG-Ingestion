CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'docx')),
    checksum TEXT NOT NULL,
    document_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('registered', 'review_ready', 'approved', 'validated', 'low_confidence', 'indexed', 'failed')),
    parser_name TEXT,
    parser_version TEXT,
    collection_name TEXT,
    error_message TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    indexed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS document_versions (
    version_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_label TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    parser_name TEXT,
    parser_version TEXT,
    status TEXT NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT true,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (document_id, source_hash)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (document_id, artifact_type)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    section_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    text_preview TEXT NOT NULL,
    source_block_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    indexed_at TIMESTAMPTZ,
    UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    run_status TEXT NOT NULL,
    parser_name TEXT,
    parser_version TEXT,
    validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_events (
    event_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES processing_runs(run_id) ON DELETE SET NULL,
    severity TEXT NOT NULL,
    event_code TEXT NOT NULL,
    event_message TEXT NOT NULL,
    event_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS idx_document_versions_current ON document_versions (document_id, is_current);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_processing_runs_document ON processing_runs (document_id, run_id DESC);
