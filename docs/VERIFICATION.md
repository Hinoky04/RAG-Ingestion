# Verification

Verification date: 24 November 2026.

## Executed checks

| Check | Observed result |
|---|---|
| Unit and integration suite | 68 passed; real-service tests enabled in the full local run |
| Delivered-code provenance | All 45 pipeline/UI/schema files matched the final-submission manifest |
| Real PDF and DOCX workflows | Upload, ingestion, artifacts, approval, local embeddings, indexing, cited retrieval, replacement reindexing, unindex and deletion passed |
| Database and vector store | PostgreSQL 17 and ChromaDB exercised in an isolated test environment |
| UI | All four Streamlit pages rendered and navigated without reported exceptions/errors |
| Startup | Streamlit HTTP health returned 200; PowerShell launcher also verified |
| Dependency consistency | `pip check` passed |
| Corpus structural audit | 47 files, 657 chunks; aggregate values below reproduced |

The embedding integration checks used the actual cached `BAAI/bge-small-en-v1.5` model, not fake embeddings. Integration tests used a disposable database. Generated logs, XML reports and runtime outputs are not included in Git.

## Repeat the fast suite

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q -m "not integration"
```

CI runs the service-independent suite; the full local run additionally enabled six integration cases. For those checks, set `RAG_TEST_DATABASE_URL` to a disposable database named `*_test` and `RAG_TEST_MODEL_CACHE` to an existing model cache, then run `python -m pytest -q`. Do not use the normal application database for tests.

## Reported corpus audit

| Signal | Count |
|---|---:|
| Documents | 47: 24 PDF, 23 DOCX |
| Chunks | 657 |
| Short chunks | 175 |
| Within-document normalized duplicate occurrences | 0 |
| Corpus-wide normalized duplicate occurrences | 95 |
| Chunks without locator | 0 |

The corpus contains related PDF/DOCX pairs. These are structural diagnostics and aggregate-repeatability evidence, not retrieval accuracy, semantic completeness or 47 independent content sources. Running the audit requires a local corpus, which is not distributed here.

## Scope of the evidence

The checks cover the tested workflows and corpus, not every possible layout or failure mode. Streamlit AppTest exercises page execution and navigation; it is not pixel-level browser-layout verification. The workbench does not generate final LLM answers. Some installed PyMuPDF/SWIG deprecation warnings remain nonfatal.

PostHog is pinned to the pre-v6 API expected by the delivered Chroma release; see the [upstream compatibility issue](https://github.com/chroma-core/chroma/issues/4966). The original seven top-level dependency versions are retained.
