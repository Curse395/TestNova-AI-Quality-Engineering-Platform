import pytest

from app.services.retrieval_evaluation import evaluate_retrieval


def test_evaluation_reports_precision_recall_mrr_and_source_attribution():
    results = {
        "login": [
            {"chunk_id": 101, "document_id": 1},
            {"chunk_id": 101, "document_id": 1},
            {"chunk_id": 102, "document_id": 999},
        ],
        "checkout": [
            {"chunk_id": 201, "document_id": 5},
        ],
    }

    metrics = evaluate_retrieval(
        results,
        {"login": {101, 103}, "checkout": {201}},
        {"login": {101: 1, 102: 2}, "checkout": {201: 5}},
        k=2,
    )

    assert metrics["precision_at_k"] == pytest.approx(0.5)
    assert metrics["recall_at_k"] == pytest.approx(0.75)
    assert metrics["mrr"] == pytest.approx(1.0)
    assert metrics["source_attribution_accuracy"] == pytest.approx(2 / 3)
    assert metrics["source_attribution_checked"] == 3
    assert metrics["per_query"]["login"]["retrieved_count"] == 2


def test_evaluation_handles_empty_results_and_requires_positive_k():
    metrics = evaluate_retrieval({}, {"query": {1}}, k=3)

    assert metrics["precision_at_k"] == 0
    assert metrics["recall_at_k"] == 0
    assert metrics["mrr"] == 0
    with pytest.raises(ValueError, match="at least one"):
        evaluate_retrieval({}, {}, k=0)
