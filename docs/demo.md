# Demo

1. Start PostgreSQL and configure the ignored `.env.local` connection string.
2. Run `./run.ps1` from the repository root.
3. In **Upload & history**, upload a text-based PDF or DOCX.
4. In **Result review**, inspect the chunks, warnings and downloadable artifacts.
5. Approve a review-ready document, then index it into `rag_ingestion`.
6. In **Retrieval**, ask a supported question and inspect the evidence and citation.
7. To re-process an indexed document, first remove it from the index, process/review again and approve before indexing.

Repeated indexing replaces the document's vectors. PostgreSQL and vector operations are separate transactions; failures may require a retry. This demo does not establish answer-generation or labelled retrieval accuracy.
