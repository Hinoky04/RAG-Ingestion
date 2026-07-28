# Progress Tracking

This document records the current narrowed state of the repository.

## Current Direction

The repository has been narrowed into a research-intern MVP focused on:

- PDF and DOCX ingestion
- PostgreSQL document tracking
- ChromaDB indexing
- retrieval verification

The main path no longer treats HTML ingestion, Markdown ingestion, Marker-based parsing, or dual backend support as active scope.

## Implemented Main Path

```text
source file
-> register
-> parse
-> clean
-> canonical JSON
-> Markdown preview
-> chunk
-> validate
-> PostgreSQL tracking
-> ChromaDB
-> retrieval check
```

## Active Parsers

- `src/parsers/pdf_parser.py`
- `src/parsers/docx_parser.py`

## Active Control Plane

- `src/workspace/postgres_workspace.py`
- `src/workspace/service.py`
- `src/workspace/models.py`

## Active Retrieval Stack

- `src/indexing/embedder.py`
- `src/indexing/chroma_store.py`
- `src/retrieval/searcher.py`

## Streamlit Role

The Streamlit app is an ingestion workspace, not a chatbot.

Current operator flow:

```text
upload PDF / DOCX
-> register
-> parse automatically
-> inspect artifacts
-> validate automatically
-> index validated document
-> run retrieval verification
```

## Current Cleanup Applied

- SQLite workspace removed from the active repo path
- HTML parser removed from the active repo path
- Markdown parser removed from the active repo path
- Marker parser removed from the active repo path
- old extension-oriented folders removed from the active repo path

## Recommended Next Testing Step

Use `KB Articles` as the primary reality check:

1. inspect file types
2. select a small representative sample
3. ingest without bulk indexing
4. inspect JSON, Markdown, and chunk output
5. index only validated samples
6. run retrieval checks against known article facts
