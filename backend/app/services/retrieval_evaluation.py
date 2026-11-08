from collections.abc import Collection, Mapping, Sequence
from typing import Any


def evaluate_retrieval(
    results_by_query: Mapping[str, Sequence[Mapping[str, Any]]],
    relevant_chunk_ids_by_query: Mapping[str, Collection[int]],
    expected_document_ids_by_query: Mapping[str, Mapping[int, int]] | None = None,
    *,
    k: int = 5,
) -> dict[str, Any]:
    if k < 1:
        raise ValueError("Evaluation k must be at least one")

    expected_document_ids_by_query = expected_document_ids_by_query or {}
    per_query: dict[str, dict[str, float | int]] = {}
    precision_values: list[float] = []
    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    attribution_correct = 0
    attribution_checked = 0

    for query, relevant_ids in relevant_chunk_ids_by_query.items():
        relevant = set(relevant_ids)
        unique_results: list[Mapping[str, Any]] = []
        seen_chunk_ids: set[int] = set()
        for result in results_by_query.get(query, ()):
            chunk_id = result.get("chunk_id")
            if not isinstance(chunk_id, int) or chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            unique_results.append(result)
        ranked = unique_results[:k]

        relevant_ranks = [
            rank
            for rank, result in enumerate(ranked, start=1)
            if result["chunk_id"] in relevant
        ]
        precision = len(relevant_ranks) / k
        recall = len(relevant_ranks) / len(relevant) if relevant else 0.0
        reciprocal_rank = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
        per_query[query] = {
            "precision_at_k": precision,
            "recall_at_k": recall,
            "reciprocal_rank": reciprocal_rank,
            "retrieved_count": len(ranked),
        }
        precision_values.append(precision)
        recall_values.append(recall)
        reciprocal_ranks.append(reciprocal_rank)

        expected_documents = expected_document_ids_by_query.get(query, {})
        for result in ranked:
            chunk_id = result["chunk_id"]
            if chunk_id not in expected_documents:
                continue
            attribution_checked += 1
            if result.get("document_id") == expected_documents[chunk_id]:
                attribution_correct += 1

    query_count = len(per_query)
    return {
        "k": k,
        "query_count": query_count,
        "precision_at_k": (
            sum(precision_values) / query_count if query_count else 0.0
        ),
        "recall_at_k": sum(recall_values) / query_count if query_count else 0.0,
        "mrr": sum(reciprocal_ranks) / query_count if query_count else 0.0,
        "source_attribution_accuracy": (
            attribution_correct / attribution_checked if attribution_checked else 0.0
        ),
        "source_attribution_checked": attribution_checked,
        "per_query": per_query,
    }
