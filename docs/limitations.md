# Limitations

- Only text-based PDF and DOCX files are supported. Scanned PDFs require OCR, which is outside this MVP.
- Parser validation checks structural output, not business correctness.
- Retrieval evaluation is a small keyword-based smoke test, not a benchmark.
- PostgreSQL and ChromaDB run locally; this repository does not include production deployment, authentication, or authorization.
- Local input datasets are gitignored and source filenames are never renamed by the pipeline.
