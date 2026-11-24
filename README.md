# Local RAG Document Workbench

[![Tests](https://github.com/Hinoky04/RAG-Ingestion/actions/workflows/tests.yml/badge.svg)](https://github.com/Hinoky04/RAG-Ingestion/actions/workflows/tests.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)

A local-first PDF/DOCX ingestion and retrieval workbench built during a research internship. It preserves document structure and provenance, makes generated chunks inspectable, and requires human approval before indexing.

**Engineering focus:** format-specific parsing, table context, reproducible artifacts, workflow state and citation-backed retrieval. PostgreSQL tracks the lifecycle; local BGE embeddings and ChromaDB provide semantic search.

[Final internship report](<docs/Research Internship Report.pdf>) · [Architecture](docs/architecture.md) · [Demo walkthrough](docs/demo.md) · [Verification](docs/VERIFICATION.md)

The delivered pipeline is preserved as the final internship baseline. See [provenance](docs/BASELINE.md) for the boundary between that implementation and maintained packaging/tests.

## Workflow

```mermaid
flowchart LR
    A[PDF / DOCX] --> B[Parse and canonicalize]
    B --> C[Clean and construct chunks]
    C --> D[Review JSON and Markdown]
    D --> E[Human approval]
    E --> F[Local BGE embeddings]
    F --> G[ChromaDB]
    G --> H[Retrieved evidence and citations]
    D -. workflow and provenance .-> I[(PostgreSQL)]
```

## Features

- Separate PDF and DOCX parsers with shared canonical/block/chunk schemas.
- Heading-, page- and table-aware chunks with source context.
- Downloadable canonical JSON, chunks JSON and Markdown review artifacts.
- Explicit approval before indexing.
- Local `BAAI/bge-small-en-v1.5` embeddings and per-document replacement indexing.
- Streamlit overview, upload/history, result review and retrieval screens.
- Inspectable lifecycle and provenance records in PostgreSQL.

This workbench does not generate final LLM answers or include OCR, enterprise access control or production deployment.

## Run on Windows

Requires Python 3.11+, PostgreSQL and a local embedding cache. Run commands from this repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Use an existing application database or create a separate role/database. Put your actual connection in the **ignored** `.env.local`:

```dotenv
WORKSPACE_DATABASE_URL=postgresql://YOUR_USER:YOUR_PASSWORD@127.0.0.1:5432/rag_ingestion
```

`run.ps1` reads this file for the current process; existing environment settings take precedence. The application initializes `db/schema.sql`, so its database role needs create/alter permissions for these tables. Use a database role and password appropriate for your local installation.

Bootstrap the model once while online:

```powershell
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-small-en-v1.5', cache_dir='.cache/huggingface')"
```

Start the workbench:

```powershell
.\run.ps1
# Optional alternative port:
.\run.ps1 -Port 8502
```

Open [localhost:8501](http://localhost:8501). If using Streamlit directly, set the connection variable first:

```powershell
$env:WORKSPACE_DATABASE_URL='postgresql://YOUR_USER:YOUR_PASSWORD@127.0.0.1:5432/rag_ingestion'
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Processing and review do not need the embedding model. Indexing and retrieval use the cached model with `local_files_only=True`.

## Demo

Upload a PDF or DOCX in **Upload & history**, inspect it in **Result review**, approve and index it, then ask a supported question in **Retrieval**. Inspect the evidence and citation. Remove indexed documents from the index before re-processing them.

See [the demo](docs/demo.md), [architecture](docs/architecture.md) and [limitations](docs/limitations.md).

## Tests and verification

Fast suite without external services:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

Opt-in integration checks use **real PostgreSQL, local BGE embeddings, ChromaDB and Streamlit AppTest**. They write data: use a disposable database named `*_test`, not the application database.

```powershell
$env:RAG_TEST_DATABASE_URL='postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/rag_ingestion_test'
$env:RAG_TEST_MODEL_CACHE=(Resolve-Path '.cache/huggingface').Path
.\.venv\Scripts\python.exe -m pytest -q
```

Observed checks and their limits are in [the verification record](docs/VERIFICATION.md). Pipeline hashes are checked against [the confirmed submission](docs/BASELINE.md).

## Historical corpus audit

The delivered 47-file corpus (24 PDF, 23 DOCX) produces 657 chunks: 175 short chunks, 95 corpus-wide normalized duplicate occurrences, zero within-document duplicate occurrences and zero chunks without a locator. These are structural diagnostics, not retrieval accuracy or proof of semantic completeness. Related PDF/DOCX pairs mean the files are not 47 independent sources.

With the local `Example-Dataset/` available:

```powershell
.\.venv\Scripts\python.exe -m sourcecode.evaluation.quality_audit --raw-dir Example-Dataset --json
```

Local datasets, uploads, model caches and databases are not tracked. A fresh clone needs its own corpus, or the retained submission's example corpus, before running this audit.

## Repository layout

```text
sourcecode/                 Delivered pipeline; preserved unchanged
  parsers/                  PDF and DOCX parsing
  processing/               Cleaning and format-aware chunking
  representation/           Schemas and Markdown artifacts
  pipeline/                 Ingestion and indexing
  workspace/                PostgreSQL lifecycle and file management
  indexing/                 Local embeddings and ChromaDB
  retrieval/                Search and diversification
  evaluation/               Structural corpus audit
db/schema.sql               Delivered schema
streamlit_app.py            Delivered interface
run.ps1                     Local configuration/startup helper
tests/                      Unit and opt-in integration checks
docs/                       Report, architecture and verification
```

Raw documents, generated artifacts, database contents, credentials, model caches and virtual environments are intentionally excluded from this repository. Supply your own local documents to explore the workflow.
