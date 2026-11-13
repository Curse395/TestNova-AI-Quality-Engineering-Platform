import hashlib
import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = (
    BACKEND_ROOT
    / "evaluation_results"
    / "comparison"
    / "quality_review.json"
)


def test_quality_review_artifact_covers_all_outputs_and_pending_human_review():
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    dataset_path = (REVIEW_PATH.parent / review["dataset"]["path"]).resolve()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset_examples = {item["id"]: item for item in dataset["examples"]}
    assert review["review_provenance"] == "assistant_preliminary_not_human_review"
    assert review["automated_findings_and_human_ratings_are_separate"] is True
    assert review["all_human_review_fields_pending"] is True
    assert len(review["providers"]) == 2

    total_cases = 0
    for provider in review["providers"]:
        assert provider["dataset_version"] == "1.0.0"
        report_path = (REVIEW_PATH.parent / provider["source_report"]).resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["configuration"]["provider"] == provider["provider"]
        assert report["configuration"]["model"] == provider["model"]
        assert len(provider["examples"]) == 5

        report_results = {item["example_id"]: item for item in report["results"]}
        for example in provider["examples"]:
            raw_result = report_results[example["example_id"]]
            raw_hash = hashlib.sha256(
                raw_result["raw_output"].encode("utf-8")
            ).hexdigest()
            generated_cases = json.loads(raw_result["raw_output"])["test_cases"]
            assert example["raw_output_sha256"] == raw_hash
            assert example["human_review"]["status"] == "pending"
            assert example["human_review"]["reviewer_decision"] is None
            assert example["human_review"]["reviewer_comments"] is None
            assert len(example["cases"]) == len(
                generated_cases
            )
            for index, case in enumerate(example["cases"]):
                total_cases += 1
                assert case["test_case"] == generated_cases[index]
                supplied_evidence_ids = {
                    item["id"]
                    for item in dataset_examples[example["example_id"]][
                        "evidence_chunks"
                    ]
                }
                assert set(case["test_case"]["evidence_chunk_ids"]).issubset(
                    supplied_evidence_ids
                )
                assert case["preliminary_assessment"]["provenance"] == (
                    "assistant_preliminary_not_human_review"
                )
                assert case["human_review"]["status"] == "pending"
                assert case["human_review"]["final_rating"] is None
                assert case["human_review"]["reviewer_decision"] is None
                assert case["human_review"]["reviewer_comments"] is None
                assert case["automated_findings"]["semantic_entailment_proven"] is False
                for dimension in (
                    "evidence_traceability",
                    "requirement_coverage",
                    "scenario_correctness",
                    "action_clarity",
                    "expected_result_specificity",
                    "unsupported_assumptions",
                    "redundancy",
                    "practical_usefulness",
                ):
                    assert dimension in case["preliminary_assessment"]
                    assert dimension in case["human_review"]["dimension_ratings"]

    assert total_cases == 14
    assert review["dataset"]["path"] == "../../evaluation_datasets/test_case_generation_v1.json"
