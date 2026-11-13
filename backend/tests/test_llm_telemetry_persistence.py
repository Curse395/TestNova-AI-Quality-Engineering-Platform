import hashlib
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import config
from app.evaluation import benchmark_cli
from app.evaluation.benchmark import create_historical_cost_report
from app.llm.contracts import (
    GenerationParameters,
    LLMGenerationRequest,
    LLMResponse,
)
from app.llm.router import LLMRouter
from app.llm.telemetry import (
    JsonlLLMTelemetryService,
    LLMCallTelemetry,
    get_persisted_telemetry_summary,
)


def _attempt(
    *,
    provider="gemini",
    model="gemini-test",
    input_tokens=100,
    output_tokens=50,
    request_success=True,
):
    now = datetime.now(timezone.utc)
    return LLMCallTelemetry(
        provider=provider,
        model=model,
        request_timestamp=now,
        completion_timestamp=now,
        latency_ms=12.5,
        success=request_success,
        error_category=None if request_success else "provider_api",
        input_token_count=input_tokens,
        output_token_count=output_tokens,
        total_token_count=(
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        request_id="request-1",
        attempt_number=1,
        is_fallback_attempt=False,
        fallback_attempted=False,
        fallback_succeeded=False,
        primary_provider=provider,
        primary_model=model,
        final_provider=provider,
        final_model=model,
        request_success=request_success,
    )


def _service(path, **kwargs):
    return JsonlLLMTelemetryService(
        storage_path=path,
        load_existing=False,
        **kwargs,
    )


def test_jsonl_records_reload_in_a_fresh_service_and_read_only_summary(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "nested" / "llm.jsonl"
    first = JsonlLLMTelemetryService(
        {"gemini": {"gemini-test": {
            "input_per_million_tokens": 2.0,
            "output_per_million_tokens": 4.0,
        }}},
        "USD",
        pricing_version="verified-2026-11",
        storage_path=path,
    )
    first.record_request([_attempt()])

    restarted = JsonlLLMTelemetryService(
        storage_path=path,
        load_existing=True,
    )
    summary = restarted.get_summary()

    assert summary.total_calls == 1
    assert summary.successful_calls == 1
    assert summary.total_input_tokens == 100
    record = restarted.get_recent_records()[0]
    assert record.estimated_cost == pytest.approx(0.0004)
    assert record.pricing_config_version == "verified-2026-11"
    assert record.input_price_per_million_tokens == 2.0
    assert record.output_price_per_million_tokens == 4.0
    original_bytes = path.read_bytes()
    monkeypatch.setattr(config.settings, "LLM_PRICING", {})
    monkeypatch.setattr(config.settings, "LLM_PRICING_CURRENCY", None)
    monkeypatch.setattr(config.settings, "LLM_PRICING_VERSION", None)
    monkeypatch.setattr(config.settings, "LLM_TELEMETRY_PATH", str(path))
    monkeypatch.setattr(config.settings, "LLM_TELEMETRY_MAX_BYTES", 100000)
    monkeypatch.setattr(config.settings, "LLM_TELEMETRY_BACKUP_COUNT", 5)
    assert get_persisted_telemetry_summary().total_calls == 1
    assert path.read_bytes() == original_bytes


def test_malformed_and_incomplete_lines_are_skipped_safely(tmp_path, caplog):
    path = tmp_path / "telemetry.jsonl"
    service = _service(path)
    service.record_request([_attempt()])
    with path.open("a", encoding="utf-8") as file:
        file.write("{broken json\n")
        file.write(json.dumps({"schema_version": "1.0.0", "attempts": [{}]}) + "\n")
        file.write(json.dumps({"schema_version": "9.0.0", "attempts": []}) + "\n")
    with path.open("ab") as file:
        file.write(b"\xff\n")

    restarted = JsonlLLMTelemetryService(storage_path=path)

    assert restarted.get_summary().total_calls == 1
    assert "Skipping malformed LLM telemetry record" in caplog.text
    assert "system prompt" not in caplog.text


def test_concurrent_threads_append_complete_jsonl_events(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    worker_count = 8
    records_per_worker = 25
    services = [_service(path) for _ in range(worker_count)]

    def write_records(worker):
        for index in range(records_per_worker):
            services[worker].record_request(
                [replace(_attempt(), request_id=f"{worker}-{index}")]
            )

    threads = [
        threading.Thread(target=write_records, args=(worker,))
        for worker in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == worker_count * records_per_worker
    assert all(json.loads(line)["attempts"] for line in lines)
    assert JsonlLLMTelemetryService(storage_path=path).get_summary().total_calls == len(lines)


def test_rotation_bounds_retained_jsonl_history(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    service = JsonlLLMTelemetryService(
        storage_path=path,
        max_bytes=700,
        backup_count=2,
        load_existing=False,
    )
    for index in range(12):
        service.record_request([replace(_attempt(), request_id=f"request-{index}")])

    retained_files = list(tmp_path.glob("telemetry.jsonl*"))
    reloaded = JsonlLLMTelemetryService(
        storage_path=path,
        max_bytes=700,
        backup_count=2,
    )
    assert len(retained_files) <= 3
    assert 0 < reloaded.get_summary().total_calls < 12
    assert service.get_summary().total_calls == 12


def test_telemetry_persistence_failure_does_not_fail_successful_generation(
    tmp_path,
    caplog,
):
    blocking_parent = tmp_path / "not-a-directory"
    blocking_parent.write_text("occupied", encoding="utf-8")
    telemetry = JsonlLLMTelemetryService(
        storage_path=blocking_parent / "telemetry.jsonl",
        load_existing=False,
    )

    class SuccessfulProvider:
        provider_name = "gemini"
        model_name = "gemini-test"

        def generate(self, request):
            return LLMResponse(
                provider="gemini",
                model="gemini-test",
                success=True,
                text="valid response",
                stage="complete",
                input_token_count=1,
                output_token_count=1,
            )

    request = LLMGenerationRequest(
        provider="gemini",
        model="gemini-test",
        system_prompt="not persisted",
        user_prompt="not persisted",
        generation_parameters=GenerationParameters(
            temperature=0,
            max_output_tokens=10,
            top_p=1,
            top_k=1,
        ),
    )
    response = LLMRouter(
        SuccessfulProvider(),
        telemetry_service=telemetry,
    ).generate(request)

    assert response.success is True
    assert response.text == "valid response"
    assert "Unable to persist LLM telemetry" in caplog.text
    assert "not persisted" not in caplog.text


def test_missing_usage_or_pricing_keeps_cost_unknown(tmp_path):
    configured = _service(
        tmp_path / "configured.jsonl",
        pricing={"gemini": {"gemini-test": {
            "input_per_million_tokens": 5.0,
            "output_per_million_tokens": 10.0,
        }}},
        currency="USD",
    )
    configured.record_request(
        [_attempt(input_tokens=None, output_tokens=50)]
    )
    no_pricing = _service(tmp_path / "unpriced.jsonl")
    no_pricing.record_request([_attempt()])

    assert configured.get_recent_records()[0].estimated_cost is None
    assert no_pricing.get_recent_records()[0].estimated_cost is None
    assert configured.get_summary().estimated_total_cost is None
    assert no_pricing.get_summary().estimated_cost_coverage == 0


def test_configured_cost_uses_separate_per_million_rates_and_fingerprint(tmp_path):
    pricing = {
        "gemini": {"gemini-test": {
            "input_per_million_tokens": 2.0,
            "output_per_million_tokens": 4.0,
        }}
    }
    service = _service(
        tmp_path / "priced.jsonl",
        pricing=pricing,
        currency="usd",
    )
    service.record_request([_attempt()])
    record = service.get_recent_records()[0]
    restarted = JsonlLLMTelemetryService(
        storage_path=tmp_path / "priced.jsonl",
    ).get_recent_records()[0]

    assert record.estimated_cost == pytest.approx(
        (100 * 2.0 + 50 * 4.0) / 1_000_000
    )
    assert record.estimated_cost_currency == "USD"
    assert record.pricing_config_version.startswith("sha256:")
    assert restarted.pricing_config_version == record.pricing_config_version
    assert restarted.estimated_cost == record.estimated_cost


def test_historical_cost_sidecar_is_reproducible_and_does_not_mutate_source():
    source = {
        "benchmark_run_id": "old-run",
        "dataset": {"version": "1.0.0"},
        "configuration": {"execution_mode": "live"},
        "results": [{
            "example_id": "example-1",
            "attempts": [{
                "provider": "gemini",
                "model": "gemini-test",
                "attempt_number": 1,
                "input_token_count": 100,
                "output_token_count": 50,
            }],
        }],
    }
    before = json.dumps(source, sort_keys=True)
    pricing = {"gemini": {"gemini-test": {
        "input_per_million_tokens": 2.0,
        "output_per_million_tokens": 4.0,
    }}}
    first = create_historical_cost_report(
        source,
        pricing=pricing,
        currency="USD",
        pricing_version="verified-2026-11",
        source_sha256="source-digest",
    )
    second = create_historical_cost_report(
        source,
        pricing=pricing,
        currency="USD",
        pricing_version="verified-2026-11",
        source_sha256="source-digest",
    )

    assert first == second
    assert first["attempts"][0]["estimated_cost"] == pytest.approx(0.0004)
    assert first["attempts"][0]["pricing_config_version"] == "verified-2026-11"
    assert first["source_report_sha256"] == "source-digest"
    assert json.dumps(source, sort_keys=True) == before


def test_historical_cost_stays_unknown_for_missing_usage_or_pricing():
    report = {
        "benchmark_run_id": "old-run",
        "configuration": {"execution_mode": "live"},
        "results": [{
            "example_id": "example-1",
            "attempts": [{
                "provider": "groq",
                "model": "unpriced-model",
                "attempt_number": 1,
                "input_token_count": 100,
                "output_token_count": 20,
            }],
        }],
    }
    priced = create_historical_cost_report(
        report,
        pricing={"groq": {"priced-model": {
            "input_per_million_tokens": 1.0,
            "output_per_million_tokens": 2.0,
        }}},
        currency="USD",
    )
    missing_usage = json.loads(json.dumps(report))
    missing_usage["results"][0]["attempts"][0]["model"] = "priced-model"
    missing_usage["results"][0]["attempts"][0]["output_token_count"] = None
    missing = create_historical_cost_report(
        missing_usage,
        pricing={"groq": {"priced-model": {
            "input_per_million_tokens": 1.0,
            "output_per_million_tokens": 2.0,
        }}},
        currency="USD",
    )

    assert priced["total_estimated_cost"] is None
    assert priced["attempts"][0]["estimated_cost"] is None
    assert missing["attempts"][0]["estimated_cost"] is None
    assert missing["cost_coverage"] == 0


def test_historical_cost_report_never_prices_mocked_latency_or_cost():
    report = {
        "benchmark_run_id": "mock-run",
        "configuration": {"execution_mode": "mocked"},
        "results": [{
            "example_id": "example-1",
            "attempts": [{
                "provider": "gemini",
                "model": "gemini-test",
                "attempt_number": 1,
                "input_token_count": 100,
                "output_token_count": 50,
            }],
        }],
    }

    cost_report = create_historical_cost_report(
        report,
        pricing={"gemini": {"gemini-test": {
            "input_per_million_tokens": 1.0,
            "output_per_million_tokens": 2.0,
        }}},
        currency="USD",
    )

    assert cost_report["measurement"] == "not_measured_mocked"
    assert cost_report["total_estimated_cost"] is None
    assert cost_report["attempts"][0]["estimated_cost"] is None


def test_cost_cli_writes_a_separate_historical_sidecar_without_overwrite(
    tmp_path,
    monkeypatch,
):
    source_path = tmp_path / "benchmark.json"
    output_path = tmp_path / "cost.json"
    source = {
        "benchmark_run_id": "historical-run",
        "dataset": {"version": "1.0.0"},
        "configuration": {"execution_mode": "live"},
        "results": [{
            "example_id": "example-1",
            "attempts": [{
                "provider": "gemini",
                "model": "gemini-test",
                "attempt_number": 1,
                "input_token_count": 100,
                "output_token_count": 50,
            }],
        }],
    }
    source_path.write_text(json.dumps(source), encoding="utf-8")
    source_digest_before = source_path.read_bytes()
    monkeypatch.setattr(
        benchmark_cli,
        "settings",
        SimpleNamespace(
            LLM_PRICING={"gemini": {"gemini-test": {
                "input_per_million_tokens": 2.0,
                "output_per_million_tokens": 4.0,
            }}},
            LLM_PRICING_CURRENCY="USD",
            LLM_PRICING_VERSION="verified-test",
        ),
    )

    assert benchmark_cli.main([
        "cost",
        str(source_path),
        "--output",
        str(output_path),
    ]) == 0

    cost_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert cost_report["source_report_sha256"] == hashlib.sha256(
        source_digest_before
    ).hexdigest()
    assert cost_report["attempts"][0]["estimated_cost"] == pytest.approx(0.0004)
    assert cost_report["pricing_config_version"] == "verified-test"
    assert source_path.read_bytes() == source_digest_before
    assert benchmark_cli.main([
        "cost",
        str(source_path),
        "--output",
        str(output_path),
    ]) == 2
