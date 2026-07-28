# Research Intern RAG Ingestion MVP

A local-first RAG ingestion MVP focused on one realistic goal:

```text
upload knowledge documents
-> parse them
-> clean and chunk them
-> track document state and artifacts in PostgreSQL
-> index validated chunks into ChromaDB
-> verify retrieval returns the correct chunks
```

This repository is intentionally not presented as a full production chatbot.
The current scope is document ingestion, control-plane tracking, vector indexing, and retrieval verification.

## Project Goal

This project is designed to be a credible research intern deliverable for Daythree.
The main value is a clean and inspectable ingestion pipeline for KB-style documents, not a fake end-to-end enterprise AI product.

## Current Scope

- PDF ingestion with PyMuPDF
- DOCX ingestion with python-docx
- Conservative cleaning and chunking
- PostgreSQL document lifecycle tracking
- ChromaDB indexing
- Retrieval verification with citations
- Streamlit workspace for upload, inspection, validation, and indexing

## Why This Scope

The realistic target is to prove that the ingestion pipeline works well:

- files can be registered
- parser output can be inspected
- chunks can be traced back to source documents
- validated chunks can be indexed
- retrieval can be checked against expected knowledge

That is a strong intern-scope milestone on its own.

## Active Pipeline

```text
PDF / DOCX
-> source registration
-> parsing
-> conservative cleaning
-> canonical JSON
-> Markdown preview
-> chunking
-> automated validation
-> PostgreSQL tracking
-> ChromaDB indexing
-> retrieval verification
```

## Tech Stack

- Python 3.11
- PyMuPDF
- python-docx
- Pydantic
- PostgreSQL with `psycopg[binary]`
- Sentence Transformers
- `BAAI/bge-small-en-v1.5`
- ChromaDB
- Streamlit

## Repository Structure

```text
src/
  registry/          source registration and checksum logic
  parsers/           active PDF and DOCX parsers
  processing/        cleaning and chunking
  representation/    canonical schemas and Markdown builder
  indexing/          embeddings and ChromaDB storage
  retrieval/         retrieval with citation metadata
  pipeline/          ingestion and indexing services / CLIs
  workspace/         PostgreSQL-backed control plane

docs/
  progress_tracking.md
  known_limitations_and_fallbacks.md
  postgresql_schema.md
  demo_walkthrough.md
  project_positioning.md

streamlit_app.py     local ingestion workspace UI
```

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set local model cache variables:

```powershell
$env:HF_HOME=".cache/huggingface"
$env:TRANSFORMERS_OFFLINE="1"
$env:HF_HUB_OFFLINE="1"
```

Set the PostgreSQL connection string:

```powershell
$env:WORKSPACE_DATABASE_URL="postgresql://user:password@localhost:5432/rag_workspace"
```

## Example Commands

Register PDF files:

```powershell
python -m src.registry.source_registry --raw-dir "data/raw/client_a/sop" --output "data/processed/registry_client_a_pdf.json" --extensions pdf
```

Parse, clean, preview, and chunk:

```powershell
python -m src.pipeline.ingest_pipeline --registry "data/processed/registry_client_a_pdf.json" --output-dir "data/processed/documents_cleaned" --markdown-dir "data/processed/markdown_cleaned" --chunk-dir "data/processed/chunks_cleaned"
```

Index chunks:

```powershell
python -m src.pipeline.index_pipeline --chunk-dir "data/processed/chunks_cleaned" --collection "daythree_demo_clean" --persist-dir "data/processed/chroma"
```

Run retrieval:

```powershell
python -m src.retrieval.searcher "When must Client A refund be escalated?" --collection "daythree_demo_clean" --persist-dir "data/processed/chroma" --top-k 3
```

Launch the Streamlit workspace:

```powershell
streamlit run streamlit_app.py
```

## What Is Implemented

- PDF source registration with checksum tracking
- PDF parsing with heading/list/table heuristics
- DOCX parsing for paragraphs, headings, lists, and simple tables
- Conservative text cleaning
- Canonical JSON generation
- Markdown preview generation
- Defensive chunking
- Local embedding generation
- Persistent ChromaDB indexing
- Retrieval with citation metadata
- PostgreSQL tracking for documents, artifacts, chunks, runs, and validation events
- Streamlit ingestion workspace

## What Is Not Implemented Yet

- Final answer generation
- OCR for scanned PDFs
- Semantic validation of business correctness
- Full permission enforcement
- Production deployment hardening

## Key Documents

- [docs/project_positioning.md](docs/project_positioning.md)
- [docs/demo_walkthrough.md](docs/demo_walkthrough.md)
- [docs/postgresql_schema.md](docs/postgresql_schema.md)
- [docs/progress_tracking.md](docs/progress_tracking.md)
- [docs/known_limitations_and_fallbacks.md](docs/known_limitations_and_fallbacks.md)
- [docs/acceptance_checklist.md](docs/acceptance_checklist.md)
