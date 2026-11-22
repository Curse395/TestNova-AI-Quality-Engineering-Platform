import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evaluation.dataset import EvaluationExample
from app.schemas.test_case_schema import GeneratedTestCase
from app.llm.structured_output import validate_structured_output


class BenchmarkOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_cases: list[GeneratedTestCase] = Field(max_length=20)


_TOKEN = re.compile(r"[a-z0-9]+")
_GENERIC_WORDS = {
    "about",
    "after",
    "before",
    "case",
    "does",
    "from",
    "have",
    "into",
    "item",
    "must",
    "only",
    "should",
    "that",
    "test",
    "this",
    "when",
    "with",
}


def _normalize(value: str) -> str:
    return " ".join(_TOKEN.findall(value.lower()))


def _case_text(case: GeneratedTestCase) -> str:
    return " ".join(
        [
            case.title,
            case.description,
            case.preconditions or "",
            case.expected_result,
            *[step.action for step in case.steps],
            *[step.expected_result for step in case.steps],
        ]
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(value.lower())
        if len(token) > 3 and token not in _GENERIC_WORDS
    }


def _metric(
    numerator: int,
    denominator: int,
    **details: Any,
) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
        "applicability": "applicable" if denominator else "not_applicable",
        **details,
    }


def _quality_metrics(
    example: EvaluationExample,
    cases: list[GeneratedTestCase],
    *,
    candidate_count: int,
    schema_valid_count: int,
    generation_failed: bool,
) -> dict[str, Any]:
    expected_requirements = set(example.expected_requirement_coverage)
    covered_requirements = {
        key
        for case in cases
        for key in case.requirement_keys
        if key in expected_requirements
    }
    annotations = {
        annotation.requirement_key: set(annotation.evidence_ids)
        for annotation in example.annotations
    }
    valid_evidence_ids = {chunk.id for chunk in example.evidence_chunks}
    evidence_grounded_cases = sum(
        bool(
            set(case.evidence_chunk_ids) & valid_evidence_ids
            and any(
                key in annotations
                and set(case.evidence_chunk_ids) & annotations[key]
                for key in case.requirement_keys
            )
        )
        for case in cases
    )
    expected_categories = set(example.expected_categories)
    covered_categories = {case.category for case in cases} & expected_categories
    case_texts = [_normalize(_case_text(case)) for case in cases]
    duplicate_candidates = sum(
        any(
            SequenceMatcher(None, text, prior).ratio() >= 0.9
            for prior in case_texts[:index]
        )
        for index, text in enumerate(case_texts)
    )
    steps = [step for case in cases for step in case.steps]
    complete_steps = sum(
        len(step.action.strip()) >= 12
        and len(step.expected_result.strip()) >= 12
        for step in steps
    )
    vague_result = re.compile(
        r"\b(?:works?|behaves?|functions?|operates?)\s+"
        r"(?:as expected|correctly|properly)\b|\bsystem behaves as expected\b",
        re.IGNORECASE,
    )
    expected_results = [
        result
        for case in cases
        for result in [
            case.expected_result,
            *(step.expected_result for step in case.steps),
        ]
    ]
    specific_results = sum(
        len(result.strip()) >= 12 and not vague_result.search(result)
        for result in expected_results
    )
    return {
        "requirement_coverage": _metric(
            len(covered_requirements),
            len(expected_requirements),
            covered=sorted(covered_requirements),
            missing=sorted(expected_requirements - covered_requirements),
        ),
        "evidence_grounding": _metric(
            evidence_grounded_cases,
            len(cases) if example.annotations else 0,
            method="case_citation_intersects_reference_annotation_evidence",
        ),
        "schema_validity": _metric(schema_valid_count, candidate_count),
        "duplicate_rate": _metric(
            duplicate_candidates,
            len(cases),
            method="case_text_sequence_similarity_at_least_0.9",
        ),
        "scenario_diversity": _metric(
            len(covered_categories),
            len(expected_categories),
            represented=sorted(covered_categories),
            missing=sorted(expected_categories - covered_categories),
        ),
        "step_completeness": _metric(
            complete_steps,
            len(steps),
            method="action_and_step_result_each_at_least_12_characters",
        ),
        "expected_result_quality": _metric(
            specific_results,
            len(expected_results),
            method="at_least_12_characters_and_not_a_vague_outcome_phrase",
        ),
        "generation_failure_rate": _metric(
            int(generation_failed),
            1,
            scope="single_evaluation_example",
        ),
    }


def _raw_candidate_schema_count(raw_output: str) -> tuple[int, int]:
    try:
        parsed = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        return 0, 0
    candidates = parsed.get("test_cases") if isinstance(parsed, dict) else None
    if not isinstance(candidates, list):
        return 0, 0
    valid_count = 0
    for candidate in candidates:
        try:
            GeneratedTestCase.model_validate(candidate)
        except (ValidationError, TypeError, ValueError):
            continue
        valid_count += 1
    return len(candidates), valid_count


def evaluate_output(example: EvaluationExample, raw_output: str) -> dict[str, Any]:
    structured = validate_structured_output(raw_output, BenchmarkOutput)
    if not structured.success or structured.value is None:
        candidate_count, schema_valid_count = _raw_candidate_schema_count(raw_output)
        return {
            "structured_output": {
                "valid": False,
                "failure_category": (
                    structured.error.category.value if structured.error else None
                ),
                "errors": (
                    structured.error.details.get("validation_errors", [])
                    if structured.error
                    else []
                ),
            },
            "evidence_accuracy": {
                "score": None,
                "citation_precision": None,
                "relevant_evidence_recall": None,
                "valid_citation_count": 0,
                "invalid_citation_count": 0,
                "unsupported_claim_rate": None,
                "unsupported_claim_detection": "not_scored_invalid_structure",
            },
            "requirement_coverage": {
                "score": None,
                "covered": [],
                "missing": list(example.expected_requirement_coverage),
                "unexpected": [],
            },
            "category_coverage": {
                "score": None,
                "covered": [],
                "missing": list(example.expected_categories),
            },
            "usefulness": {
                "test_case_usefulness_score": None,
                "deterministic_components": {},
                "human_review_required": True,
            },
            "quality_metrics": _quality_metrics(
                example,
                [],
                candidate_count=candidate_count,
                schema_valid_count=schema_valid_count,
                generation_failed=True,
            ),
            "generated_case_count": None,
        }

    cases = structured.value.test_cases
    candidate_count, schema_valid_count = _raw_candidate_schema_count(raw_output)
    expected_requirements = set(example.expected_requirement_coverage)
    valid_evidence_ids = {chunk.id for chunk in example.evidence_chunks}
    expected_relevant_ids = {
        evidence_id
        for annotation in example.annotations
        for evidence_id in annotation.evidence_ids
    }
    all_citations = [
        evidence_id
        for case in cases
        for evidence_id in case.evidence_chunk_ids
    ]
    valid_citations = [
        evidence_id for evidence_id in all_citations if evidence_id in valid_evidence_ids
    ]
    invalid_citation_count = len(all_citations) - len(valid_citations)
    citation_precision = (
        len(valid_citations) / len(all_citations)
        if all_citations
        else (1.0 if not cases else 0.0)
    )
    cited_relevant_ids = set(valid_citations) & expected_relevant_ids
    relevant_evidence_recall = (
        len(cited_relevant_ids) / len(expected_relevant_ids)
        if expected_relevant_ids
        else (1.0 if not cases else 0.0)
    )
    evidence_chunks_by_id = {
        chunk.id: chunk.content for chunk in example.evidence_chunks
    }
    specificity_scores: list[float] = []
    for case in cases:
        cited_sources = [
            evidence_chunks_by_id[item]
            for item in case.evidence_chunk_ids
            if item in evidence_chunks_by_id
        ]
        case_tokens = _tokens(_case_text(case))
        source_tokens = _tokens(" ".join(cited_sources))
        specificity_scores.append(
            len(case_tokens & source_tokens) / len(case_tokens)
            if case_tokens and source_tokens
            else 0.0
        )
    evidence_overlap_score = (
        sum(specificity_scores) / len(specificity_scores)
        if specificity_scores
        else (1.0 if not expected_requirements else 0.0)
    )
    evidence_score = (
        citation_precision + relevant_evidence_recall + evidence_overlap_score
    ) / 3

    requirement_keys = {
        requirement_key
        for case in cases
        for requirement_key in case.requirement_keys
    }
    covered_requirements = requirement_keys & expected_requirements
    unexpected_requirements = requirement_keys - expected_requirements
    requirement_coverage = (
        len(covered_requirements) / len(expected_requirements)
        if expected_requirements
        else (1.0 if not requirement_keys else 0.0)
    )
    used_categories = {case.category for case in cases}
    expected_categories = set(example.expected_categories)
    covered_categories = used_categories & expected_categories
    category_coverage = (
        len(covered_categories) / len(expected_categories)
        if expected_categories
        else (1.0 if not used_categories else 0.0)
    )

    forbidden_phrases = [_normalize(item) for item in example.unsupported_behaviors]
    case_texts = [_normalize(_case_text(case)) for case in cases]
    unsupported_cases = sum(
        any(phrase and phrase in text for phrase in forbidden_phrases)
        for text in case_texts
    )
    unsupported_claim_rate = (
        unsupported_cases / len(cases)
        if cases
        else (0.0 if not expected_requirements else None)
    )
    if cases:
        action_clarity = sum(
            len(step.action.strip()) >= 12
            for case in cases
            for step in case.steps
        ) / sum(len(case.steps) for case in cases)
        expected_result_clarity = sum(
            len(result.strip()) >= 12
            for case in cases
            for result in [
                case.expected_result,
                *[step.expected_result for step in case.steps],
            ]
        ) / sum(1 + len(case.steps) for case in cases)
        testability = sum(
            bool(case.steps)
            and all(
                bool(step.action.strip()) and bool(step.expected_result.strip())
                for step in case.steps
            )
            for case in cases
        ) / len(cases)
        specificity = sum(specificity_scores) / len(specificity_scores)
        duplicate_pairs = sum(
            SequenceMatcher(None, left, right).ratio() >= 0.9
            for index, left in enumerate(case_texts)
            for right in case_texts[index + 1 :]
        )
        pair_count = len(cases) * (len(cases) - 1) / 2
        non_redundancy = 1 - duplicate_pairs / pair_count if pair_count else 1.0
        category_precision = (
            len(covered_categories) / len(used_categories) if used_categories else 1.0
        )
        category_quality = (category_coverage + category_precision) / 2
        usefulness_score = sum(
            (
                requirement_coverage,
                action_clarity,
                expected_result_clarity,
                testability,
                specificity,
                category_quality,
                non_redundancy,
            )
        ) / 7
        usefulness_components = {
            "requirement_coverage": requirement_coverage,
            "action_clarity_length_heuristic": action_clarity,
            "expected_result_clarity_length_heuristic": expected_result_clarity,
            "testability_schema_and_step_completeness": testability,
            "evidence_specificity_token_overlap": specificity,
            "requested_category_quality": category_quality,
            "non_redundancy_similarity_heuristic": non_redundancy,
        }
    elif expected_requirements or expected_categories:
        usefulness_score = sum(
            (requirement_coverage, category_coverage, 0, 0, 0, 0, 0)
        ) / 7
        usefulness_components = {
            "requirement_coverage": requirement_coverage,
            "action_clarity_length_heuristic": 0.0,
            "expected_result_clarity_length_heuristic": 0.0,
            "testability_schema_and_step_completeness": 0.0,
            "evidence_specificity_token_overlap": 0.0,
            "requested_category_coverage": category_coverage,
            "non_redundancy_similarity_heuristic": 0.0,
        }
    else:
        usefulness_score = None
        usefulness_components = {
            "requirement_coverage": requirement_coverage,
            "requested_category_coverage": category_coverage,
        }

    return {
        "structured_output": {
            "valid": True,
            "failure_category": None,
            "errors": [],
            "required_fields_present": True,
            "category_and_priority_valid": True,
            "step_structure_valid": True,
            "valid_evidence_references": invalid_citation_count == 0,
            "fully_valid": invalid_citation_count == 0,
        },
        "evidence_accuracy": {
            "score": evidence_score,
            "citation_precision": citation_precision,
            "relevant_evidence_recall": relevant_evidence_recall,
            "cited_text_token_overlap_heuristic": evidence_overlap_score,
            "valid_citation_count": len(valid_citations),
            "invalid_citation_count": invalid_citation_count,
            "unsupported_claim_rate": unsupported_claim_rate,
            "unsupported_case_count": unsupported_cases,
            "unsupported_claim_detection": "exact_dataset_phrase_match_only",
        },
        "requirement_coverage": {
            "score": requirement_coverage,
            "covered": sorted(covered_requirements),
            "missing": sorted(expected_requirements - requirement_keys),
            "unexpected": sorted(unexpected_requirements),
        },
        "category_coverage": {
            "score": category_coverage,
            "covered": sorted(covered_categories),
            "missing": sorted(expected_categories - used_categories),
            "unexpected": sorted(used_categories - expected_categories),
        },
        "usefulness": {
            "test_case_usefulness_score": usefulness_score,
            "deterministic_components": usefulness_components,
            "human_review_required": bool(cases),
            "human_review_scores": None,
        },
        "quality_metrics": _quality_metrics(
            example,
            cases,
            candidate_count=candidate_count,
            schema_valid_count=schema_valid_count,
            generation_failed=(
                not cases
                and bool(
                    example.expected_requirement_coverage
                    or example.expected_categories
                )
            ),
        ),
        "generated_case_count": len(cases),
    }


def parse_valid_cases(raw_output: str) -> list[GeneratedTestCase]:
    result = validate_structured_output(raw_output, BenchmarkOutput)
    if not result.success or result.value is None:
        return []
    return result.value.test_cases


def evidence_reference_is_valid(case: GeneratedTestCase, example: EvaluationExample) -> bool:
    known_ids = {chunk.id for chunk in example.evidence_chunks}
    return bool(case.evidence_chunk_ids) and set(case.evidence_chunk_ids).issubset(
        known_ids
    )
