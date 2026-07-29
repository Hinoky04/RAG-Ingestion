from src.representation.schemas import RetrievalResult
from src.retrieval.searcher import diversify_results


def result(section_path: str, score: float, chunk_id: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        score=score,
        text="chunk text",
        document_id="doc-1",
        source_path="sample.docx",
        file_name="sample.docx",
        section_path=section_path,
        version="v1",
    )


def test_diversify_results_penalizes_same_section_group():
    results = [
        result("2. Product Details · Overview", 0.61, "chunk-a"),
        result("2. Product Details · MNP", 0.61, "chunk-b"),
        result("2. Product Details · Quota", 0.60, "chunk-c"),
        result("3. Eligibility and Criteria", 0.59, "chunk-d"),
    ]

    diversified = diversify_results(results, top_k=3)

    assert [item.chunk_id for item in diversified] == ["chunk-a", "chunk-d", "chunk-b"]
    assert diversified[1].section_path == "3. Eligibility and Criteria"
