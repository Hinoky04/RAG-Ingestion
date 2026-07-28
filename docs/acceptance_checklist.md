# Acceptance Checklist

Use this checklist before pushing the internship repo.

## Scope

- The README describes the repo as an ingestion and retrieval-verification MVP.
- The repo does not claim to be a finished enterprise chatbot.
- The active input formats are PDF and DOCX only.

## Code Path

- PostgreSQL is the only active workspace backend.
- HTML, Markdown, and Marker parsers are not in the active source tree.
- The Streamlit workspace accepts PDF and DOCX only.

## Data Hygiene

- `KB Articles/` remains gitignored.
- `data/raw/` and `data/processed/` remain gitignored except for placeholders.
- local caches and virtual environments are not included.

## Demo Readiness

- Uploading a sample file creates a tracked document row.
- Canonical JSON, Markdown preview, and chunks are generated.
- Validated chunks can be indexed into ChromaDB.
- Retrieval can return an expected chunk with citation metadata.

## Documentation

- README matches the current implementation.
- PostgreSQL schema doc is present.
- demo walkthrough is present.
- limitations are documented honestly.
