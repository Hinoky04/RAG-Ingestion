# Known Limitations And Fallbacks

This project is intentionally honest about its current limitations.

## 1. PDF Structure Recovery Is Heuristic

The parser can recover useful structure, but not perfect structure.
Headings, paragraphs, lists, and tables are inferred from document patterns.

Fallback:
- preserve traceability
- preserve page numbers
- let chunking fall back when structure is weak

## 2. Full Table Reconstruction Is Not Implemented

The system preserves table-like text, but it does not rebuild perfect row/column structure for every file.

Fallback:
- keep table content searchable
- keep it attached to nearby section context

## 3. DOCX Parsing Is Basic

The DOCX parser handles headings, paragraphs, list-like content, and simple tables.
It does not fully reconstruct complex Word layouts.

Fallback:
- section-level citations remain usable
- convert to PDF later if page-level citation becomes necessary

## 4. Automated Validation Checks Structure, Not Business Truth

The current validation step proves that the ingestion pipeline produced usable artifacts.
It does not prove that the extracted business meaning is semantically correct.

Fallback:
- keep indexing as an explicit operator action
- inspect outputs before trusting unfamiliar documents

## 5. OCR Is Not Implemented

Scanned PDFs and image-heavy forms may parse poorly.

Fallback:
- treat those documents as low-confidence
- add OCR only when real dataset evidence justifies it

## 6. PostgreSQL Control Plane Is Not Yet A Full Product Backend

The database tracks ingestion state well, but the project does not yet include:

- authentication
- strong role-based enforcement
- production-grade migrations
- semantic review workflows

Fallback:
- present the repo as an ingestion MVP, not a finished enterprise platform

## 7. Retrieval Verification Is Not Final Answer Generation

Good chunk retrieval is useful evidence, but it is not the same as a fully correct chatbot answer.

Fallback:
- stop the current scope at retrieval verification
- add answer generation only after the ingestion path is stable
