import json
from types import SimpleNamespace

import pytest

from app.evaluation.benchmark import (
    BenchmarkRunner,
    aggregate_results,
    compare_reports,
    render_markdown_report,
    write_comparison,
    write_report,
)
from app.evaluation.benchmark_cli import main
from app.evaluation.dataset import (
    DEFAULT_DATASET_PATH,
    EvaluationDataset,
    EvaluationExample,
    load_dataset,
)
from app.evaluation.scoring import evaluate_output
from app.llm.contracts import (
    LLMError,
    LLMErrorCategory,
    LLMResponse,
)
from app.llm.router import LLMRouter


def _case(
    *,
    evidence_ids=(71001,),
    requirement_keys=("SYN-AUTH-1",),
    category="positive",
    action="Submit the registered user's correct email and password.",
    step_result="The sign-in completes and the dashboard is displayed.",
    expected_result="The registered user is signed in and taken to the project dashboard.",
):
    return {
        "title": "Registered user signs in successfully",
        "description": "Verify the documented successful sign-in behavior.",
        "test_type": "functional",
        "category": category,
        "priority": "medium",
        "severity": "medium",
        "preconditions": "A registered user is available.",
        "steps": [{"action": action, "expected_result": step_result}],
        "expected_result": expected_result,
        "evidence_chunk_ids": list(evidence_ids),
        "requirement_keys": list(requirement_keys),
    }


def _output(cases):
    return json.dumps({"test_cases": cases})


def test_default_dataset_loads_versioned_synthetic_examples_and_traceable_refs():
    dataset = load_dataset(DEFAULT_DATASET_PATH, expected_version="1.0.0")

    assert dataset.dataset_version == "1.0.0"
    assert len(dataset.examples) == 5
    assert {
        item.scenario_type for item in dataset.examples
    } >= {"positive", "negative", "boundary", "edge", "insufficient_evidence"}
    for example in dataset.examples:
        evidence = {item.id: item.content for item in example.evidence_chunks}
        for annotation in example.annotations:
            assert any(
                annotation.evidence_quote in evidence[item]
                for item in annotation.evidence_ids
            )


def test_dataset_version_mismatch_is_rejected():
    with pytest.raises(ValueError, match="version mismatch"):
        load_dataset(DEFAULT_DATASET_PATH, expected_version="2.0.0")


def test_dataset_rejects_untraceable_annotation_and_unknown_evidence():
    example = load_dataset().examples[0].model_dump()
    example["annotations"][0]["evidence_quote"] = "not in supplied evidence"

    with pytest.raises(ValueError, match="quote is not in cited evidence"):
        EvaluationExample.model_validate(example)

    example = load_dataset().examples[0].model_dump()
    example["annotations"][0]["evidence_ids"] = [999999]
    with pytest.raises(ValueError, match="unknown evidence"):
        EvaluationExample.model_validate(example)


def test_dataset_rejects_duplicate_example_ids():
    data = load_dataset().model_dump()
    data["examples"][1]["id"] = data["examples"][0]["id"]

    with pytest.raises(ValueError, match="unique"):
        EvaluationDataset.model_validate(data)


def test_structured_output_scoring_checks_fields_schema_and_valid_evidence():
    example = load_dataset().examples[0]
    scores = evaluate_output(example, _output([_case()]))

    assert scores["structured_output"]["valid"] is True
    assert scores["structured_output"]["required_fields_present"] is True
    assert scores["structured_output"]["category_and_priority_valid"] is True
    assert scores["structured_output"]["step_structure_valid"] is True
    assert scores["structured_output"]["valid_evidence_references"] is True
    assert scores["evidence_accuracy"]["valid_citation_count"] == 1
    assert scores["evidence_accuracy"]["invalid_citation_count"] == 0
    assert scores["requirement_coverage"]["score"] == 1
    assert scores["category_coverage"]["score"] == 1


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        ("not json", "structured_output_parse"),
        ('{"test_cases":[{"title":"missing fields"}]}', "schema_validation"),
    ],
)
def test_invalid_structured_output_is_not_repaired_or_scored(raw, category):
    example = load_dataset().examples[0]

    scores = evaluate_output(example, raw)

    assert scores["structured_output"]["valid"] is False
    assert scores["structured_output"]["failure_category"] == category
    assert scores["evidence_accuracy"]["score"] is None
    assert scores["usefulness"]["test_case_usefulness_score"] is None


def test_invalid_evidence_reference_is_detected_deterministically():
    example = load_dataset().examples[0]

    scores = evaluate_output(example, _output([_case(evidence_ids=(99999,))]))

    assert scores["evidence_accuracy"]["invalid_citation_count"] == 1
    assert scores["structured_output"]["valid_evidence_references"] is False
    assert scores["structured_output"]["fully_valid"] is False
    assert scores["evidence_accuracy"]["citation_precision"] == 0
    assert scores["evidence_accuracy"]["relevant_evidence_recall"] == 0
    assert scores["evidence_accuracy"]["score"] == 0


def test_unsupported_claim_exact_match_and_usefulness_rubric():
    example = load_dataset().examples[0]
    unsupported_case = _case(
        expected_result=(
            "The user is signed in and multi-factor authentication is enabled."
        ),
    )

    scores = evaluate_output(example, _output([unsupported_case]))

    assert scores["evidence_accuracy"]["unsupported_case_count"] == 1
    assert scores["evidence_accuracy"]["unsupported_claim_rate"] == 1
    assert scores["usefulness"]["test_case_usefulness_score"] is not None
    assert scores["usefulness"]["human_review_required"] is True
    assert scores["usefulness"]["human_review_scores"] is None


def test_insufficient_evidence_reference_requires_no_invented_case():
    example = next(
        item
        for item in load_dataset().examples
        if item.scenario_type == "insufficient_evidence"
    )

    scores = evaluate_output(example, _output([]))

    assert scores["structured_output"]["valid"] is True
    assert scores["requirement_coverage"]["score"] == 1
    assert scores["category_coverage"]["score"] == 1
    assert scores["evidence_accuracy"]["unsupported_claim_rate"] == 0
    assert scores["usefulness"]["test_case_usefulness_score"] is None


def test_missing_expected_cases_receive_zero_usefulness_not_unknown():
    example = load_dataset().examples[0]

    scores = evaluate_output(example, _output([]))

    assert scores["requirement_coverage"]["score"] == 0
    assert scores["category_coverage"]["score"] == 0
    assert scores["usefulness"]["test_case_usefulness_score"] == 0


class FakeBenchmarkService:
    def __init__(self, response_factory, telemetry, provider, model):
        self.response_factory = response_factory
        self.telemetry = telemetry
        self.provider = provider
        self.model = model
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return self.response_factory(request)


def _successful_response(request):
    if "SYN-EXPORT" in request.user_prompt:
        output = {"test_cases": []}
    elif "SYN-AUTH-2" in request.user_prompt:
        output = {
            "test_cases": [
                _case(
                    evidence_ids=(71011,),
                    requirement_keys=("SYN-AUTH-2",),
                    category="negative",
                    action="Submit the sign-in form with the email field empty.",
                    step_result="The form rejects the submission and displays Email is required.",
                    expected_result="The submission is rejected and Email is required is displayed.",
                )
            ]
        }
    elif "SYN-CART" in request.user_prompt:
        output = {
            "test_cases": [
                _case(
                    evidence_ids=(71021, 71022),
                    requirement_keys=("SYN-CART-1",),
                    category="boundary",
                )
            ]
        }
    elif "SYN-RESET" in request.user_prompt:
        output = {
            "test_cases": [
                _case(
                    evidence_ids=(71031, 71032),
                    requirement_keys=("SYN-RESET-1",),
                    category="edge",
                )
            ]
        }
    else:
        output = {"test_cases": [_case()]}
    return LLMResponse(
        provider=request.provider,
        model=request.model,
        success=True,
        text=json.dumps(output),
        stage="complete",
        input_token_count=None,
        output_token_count=None,
        total_token_count=None,
        request_id=request.request_id,
    )


def _fake_factory(requests, response_factory=_successful_response):
    def create(provider, model, telemetry):
        requests.append((provider, model))
        service = FakeBenchmarkService(
            response_factory,
            telemetry,
            provider,
            model,
        )
        services.append(service)
        return service

    services = []
    return create, services


def test_runner_explicit_provider_model_and_reproducible_prompts():
    selections = []
    services = []
    factory, factory_services = _fake_factory(selections)
    runner = BenchmarkRunner.from_path(service_factory=factory)
    selected_ids = {"SYN-AUTH-POS-001"}

    first = runner.run(
        provider_name="gemini",
        model_name="explicit-gemini-model",
        run_id="fixed-run-a",
        selected_example_ids=selected_ids,
    )
    second = runner.run(
        provider_name="groq",
        model_name="explicit-groq-model",
        run_id="fixed-run-b",
        selected_example_ids=selected_ids,
    )
    services.extend(factory_services)

    assert selections == [
        ("gemini", "explicit-gemini-model"),
        ("groq", "explicit-groq-model"),
    ]
    assert first["configuration"]["fallback_enabled"] is False
    assert first["results"][0]["status"] == "completed"
    assert all(
        result["status"] == "skipped"
        for result in first["results"][1:]
    )
    assert services[0].requests[0].user_prompt == services[1].requests[0].user_prompt
    assert services[0].requests[0].system_prompt == services[1].requests[0].system_prompt
    assert services[0].requests[0].request_id != services[1].requests[0].request_id
    assert first["metrics"]["latency_ms"]["average"] is None
    assert first["metrics"]["estimated_cost"]["total"] is None


def test_runner_handles_partial_failures_and_tracks_missing_usage():
    def response_factory(request):
        if "SYN-AUTH-NEG" in request.user_prompt:
            return LLMResponse(
                provider=request.provider,
                model=request.model,
                success=False,
                text="",
                stage="provider_request",
                error="safe failure",
                error_details=LLMError(
                    category=LLMErrorCategory.RATE_LIMIT,
                    message="safe failure",
                    stage="provider_request",
                ),
            )
        return _successful_response(request)

    selections = []
    factory, _ = _fake_factory(selections, response_factory)
    runner = BenchmarkRunner.from_path(service_factory=factory)

    report = runner.run(
        provider_name="groq",
        model_name="explicit-model",
        run_id="partial-run",
        selected_example_ids={"SYN-AUTH-POS-001", "SYN-AUTH-NEG-002"},
    )

    assert report["results"][0]["status"] == "completed"
    assert report["results"][1]["status"] == "failed"
    assert report["results"][1]["failure_category"] == "rate_limit"
    assert report["metrics"]["completed_examples"] == 1
    assert report["metrics"]["failed_examples"] == 1
    assert report["metrics"]["skipped_examples"] == 3
    assert report["metrics"]["input_tokens"]["total"] is None


def test_runner_uses_stage4_attempt_telemetry_for_provider_metrics():
    class TokenProvider:
        provider_name = "gemini"
        model_name = "telemetry-test-model"

        def generate(self, request):
            return LLMResponse(
                provider=request.provider,
                model=request.model,
                success=True,
                text=_output([_case()]),
                stage="complete",
                input_token_count=123,
                output_token_count=45,
                total_token_count=168,
                request_id=request.request_id,
            )

    def factory(provider, model, telemetry):
        assert provider == "gemini"
        assert model == "telemetry-test-model"
        return SimpleNamespace(
            generate=LLMRouter(TokenProvider(), telemetry_service=telemetry).generate
        )

    report = BenchmarkRunner.from_path(service_factory=factory).run(
        provider_name="gemini",
        model_name="telemetry-test-model",
        run_id="telemetry-run",
        selected_example_ids={"SYN-AUTH-POS-001"},
        execution_mode="mocked",
    )
    attempt = report["results"][0]["attempts"][0]

    assert attempt["input_token_count"] == 123
    assert attempt["output_token_count"] == 45
    assert attempt["total_token_count"] == 168
    assert attempt["request_id"] == "telemetry-run:SYN-AUTH-POS-001"
    assert attempt["provider"] == "gemini"
    assert attempt["model"] == "telemetry-test-model"
    assert attempt["latency_ms"] is None
    assert attempt["estimated_cost"] is None
    assert report["metrics"]["input_tokens"]["total"] == 123
    assert report["metrics"]["latency_ms"]["average"] is None


def test_live_metric_aggregation_reports_attempt_and_request_latency():
    scores = {
        "structured_output": {"valid": True},
        "evidence_accuracy": {
            "score": 1.0,
            "unsupported_claim_rate": 0.0,
        },
        "requirement_coverage": {"score": 1.0},
        "usefulness": {"test_case_usefulness_score": 0.9},
    }
    results = [
        {
            "status": "completed",
            "scores": scores,
            "overall_latency_ms": 12.0,
            "attempts": [{"latency_ms": 10.0, "success": True}],
        },
        {
            "status": "failed",
            "scores": None,
            "overall_latency_ms": 35.0,
            "attempts": [{"latency_ms": 30.0, "success": False}],
        },
    ]

    metrics = aggregate_results(results, execution_mode="live")

    assert metrics["latency_ms"]["average"] == 20.0
    assert metrics["latency_ms"]["median"] == 20.0
    assert metrics["request_latency_ms"]["average"] == 23.5
    assert metrics["request_latency_ms"]["median"] == 23.5
    assert metrics["failed_call_count"] == 1
    assert metrics["estimated_cost"]["total"] is None
    assert metrics["input_tokens"]["total"] is None


def test_runner_rejects_unknown_provider_model_and_example():
    runner = BenchmarkRunner.from_path()
    with pytest.raises(ValueError, match="Provider must"):
        runner.run(provider_name="other", model_name="model")
    with pytest.raises(ValueError, match="explicitly configured"):
        runner.run(provider_name="gemini", model_name=" ")
    with pytest.raises(ValueError, match="Unknown example IDs"):
        runner.run(
            provider_name="gemini",
            model_name="model",
            selected_example_ids={"NOT-AN-EXAMPLE"},
        )


def test_report_generation_and_comparison_require_matching_dataset_selection(tmp_path):
    selections = []
    factory, _ = _fake_factory(selections)
    runner = BenchmarkRunner.from_path(service_factory=factory)
    first = runner.run(
        provider_name="gemini",
        model_name="model-a",
        run_id="run-a",
        selected_example_ids={"SYN-AUTH-POS-001"},
    )
    second = runner.run(
        provider_name="groq",
        model_name="model-b",
        run_id="run-b",
        selected_example_ids={"SYN-AUTH-POS-001"},
    )

    json_path, markdown_path = write_report(first, tmp_path / "out")

    assert json_path.exists()
    assert markdown_path.exists()
    assert "not measured (mocked)" in markdown_path.read_text(encoding="utf-8")
    assert "No model winner is declared" in render_markdown_report(first)
    comparison = compare_reports([first, second])
    assert comparison["winner"] is None
    comparison_json, comparison_markdown = write_comparison(
        comparison,
        tmp_path / "comparison",
    )
    assert comparison_json.exists()
    assert comparison_markdown.exists()
    assert "not measured (mocked)" in comparison_markdown.read_text(
        encoding="utf-8"
    )
    assert all(
        run["metrics"]["latency_ms"]["average"] is None
        and run["metrics"]["estimated_cost"]["total"] is None
        for run in comparison["runs"]
    )
    second["dataset"]["selected_example_ids"] = ["SYN-AUTH-NEG-002"]
    with pytest.raises(ValueError, match="same dataset version and example IDs"):
        compare_reports([first, second])


def test_live_cli_requires_explicit_opt_in(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "run",
                "--provider",
                "gemini",
                "--model",
                "test-model",
                "--output-dir",
                "unused",
            ]
        )

    assert exc_info.value.code == 2
    assert "--live" in capsys.readouterr().err
