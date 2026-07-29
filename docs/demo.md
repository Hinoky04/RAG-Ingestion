# Demo

1. Set `WORKSPACE_DATABASE_URL` to a running PostgreSQL database.
2. Run `streamlit run streamlit_app.py`.
3. Upload one PDF or DOCX. The source filename is preserved.
4. Show the registered document, validation status, canonical JSON, Markdown preview, and chunk list.
5. Index the validated document into `rag_ingestion`.
6. Ask a question with an answer in that article and show the returned chunk with its citation.
7. Re-parse and re-index the same document to demonstrate that old vectors are replaced.

The correct claim is: the project demonstrates traceable ingestion and retrieval verification for local documents. It does not provide answer generation, OCR, access control, or deployment hardening.
