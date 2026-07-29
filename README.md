# RAG Ingestion

A local-first research project that proves a traceable PDF/DOCX ingestion pipeline.

```text
PDF / DOCX -> parse -> clean -> chunk -> PostgreSQL tracking -> ChromaDB -> retrieval verification
```

The project is intentionally scoped to ingestion and retrieval evidence. It is not presented as a finished chatbot or enterprise RAG platform.

## What It Demonstrates

- PDF parsing with PyMuPDF and DOCX parsing with python-docx
- Canonical document JSON, Markdown previews, and retrieval chunks
- PostgreSQL lifecycle tracking for documents, checksum versions, artifacts, chunks, and validation runs
- ChromaDB indexing with source metadata and citations
- Re-index safety: old vectors for a re-parsed document are removed before current chunks are inserted
- Streamlit UI for upload, inspection, indexing, and retrieval checks

## Quick Start

Requirements: Python 3.11+ and a running PostgreSQL database. Input files stay local and the pipeline preserves their original filenames.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:WORKSPACE_DATABASE_URL="postgresql://user:password@localhost:5432/rag_ingestion"
streamlit run streamlit_app.py
```

### Local Embedding Model Bootstrap

Indexing and retrieval use `BAAI/bge-small-en-v1.5`. The application is intentionally configured with `local_files_only=True`, so it never downloads a model while a document is being indexed. Run this once with an internet connection after installing dependencies:

```powershell
.\.venv\Scripts\python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-small-en-v1.5', cache_dir='.cache/huggingface')"
```

The model is then cached under `.cache/huggingface/` and all normal indexing and retrieval runs use that local copy. The cache is local-only and should not be committed.

## Demo Flow

1. Upload a PDF or DOCX.
2. Inspect its status, canonical JSON, Markdown preview, and chunks.
3. Index the validated chunks into the `rag_ingestion` collection.
4. Ask a question whose answer appears in the uploaded document.
5. Verify the returned chunk and citation.

For the full live demo sequence, see [docs/demo.md](docs/demo.md).

## Command-Line Flow

```powershell
python -m src.registry.source_registry --raw-dir "data/raw" --output "data/processed/registry.json"
python -m src.pipeline.ingest_pipeline --registry "data/processed/registry.json"
python -m src.pipeline.index_pipeline --chunk-dir "data/processed/chunks" --collection "rag_ingestion"
python -m src.retrieval.searcher "Ask a document-specific question" --collection "rag_ingestion"
```

To run a local retrieval smoke test, copy `data/samples/evaluation_queries.example.json` to `data/samples/evaluation_queries.local.json`, replace the placeholder with questions and expected terms from your local documents, then run:

```powershell
python -m src.evaluation.test_queries
```

## Repository Layout

```text
src/
  parsers/        PDF and DOCX parsing
  processing/     cleaning and chunking
  representation/ canonical schemas and Markdown preview
  pipeline/       ingestion and indexing orchestration
  workspace/      PostgreSQL document lifecycle tracking
  indexing/       local embeddings and ChromaDB storage
  retrieval/      citation-aware vector search
db/schema.sql     PostgreSQL schema
docs/             architecture, demo, and limitations
```

## Limits

This MVP does not include OCR, answer generation, permissions, or production deployment. See [docs/limitations.md](docs/limitations.md) for the exact boundary and [docs/architecture.md](docs/architecture.md) for storage design.
