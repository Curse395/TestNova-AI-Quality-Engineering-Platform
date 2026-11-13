import hashlib
import json
import logging
import math
import os
import stat
import statistics
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)

_TELEMETRY_SCHEMA_VERSION = "1.0.0"
_DEFAULT_TELEMETRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "llm_telemetry.jsonl"
)
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_LOCK = threading.Lock()


def _lock_for_path(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PATH_LOCKS_LOCK:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


@dataclass(frozen=True)
class ModelPricing:
    input_per_million_tokens: float
    output_per_million_tokens: float

    def __post_init__(self) -> None:
        for field_name in (
            "input_per_million_tokens",
            "output_per_million_tokens",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a finite non-negative number")


@dataclass(frozen=True)
class LLMCallTelemetry:
    provider: str
    model: str
    request_timestamp: datetime
    completion_timestamp: datetime
    latency_ms: float
    success: bool
    error_category: str | None
    input_token_count: int | None
    output_token_count: int | None
    total_token_count: int | None
    request_id: str | None
    attempt_number: int
    is_fallback_attempt: bool
    fallback_attempted: bool
    fallback_succeeded: bool
    primary_provider: str
    primary_model: str
    final_provider: str
    final_model: str
    request_success: bool


@dataclass(frozen=True)
class LLMCallTelemetryRecord(LLMCallTelemetry):
    estimated_cost: float | None
    estimated_cost_currency: str | None
    cost_is_estimate: bool
    pricing_config_version: str | None = None
    pricing_currency: str | None = None
    input_price_per_million_tokens: float | None = None
    output_price_per_million_tokens: float | None = None


@dataclass(frozen=True)
class LLMTelemetrySummary:
    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float | None
    average_latency_ms: float | None
    median_latency_ms: float | None
    provider_model_usage: dict[str, int]
    total_requests: int
    successful_requests: int
    failed_requests: int
    fallback_attempts: int
    fallback_successes: int
    fallback_success_rate: float | None
    total_input_tokens: int | None
    input_token_observations: int
    total_output_tokens: int | None
    output_token_observations: int
    total_tokens: int | None
    total_token_observations: int
    estimated_total_cost: float | None
    estimated_cost_currency: str | None
    estimated_cost_calls: int
    estimated_cost_coverage: float | None
    estimated_total_cost_is_partial: bool | None
    estimated_cost_by_currency: dict[str, float] = field(default_factory=dict)


class LLMTelemetrySink(Protocol):
    def record_request(self, attempts: Sequence[LLMCallTelemetry]) -> None: ...


class InMemoryLLMTelemetryService:
    """Collects process-local LLM metrics."""

    def __init__(
        self,
        pricing: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None,
        currency: str | None = None,
        *,
        pricing_version: str | None = None,
        recent_record_limit: int = 1000,
        median_sample_limit: int = 10000,
    ) -> None:
        if recent_record_limit < 1 or median_sample_limit < 1:
            raise ValueError("Telemetry retention limits must be positive")
        self._pricing = self._parse_pricing(
            pricing if pricing is not None else {}
        )
        if self._pricing and not currency:
            raise ValueError("A currency is required when model pricing is configured")
        self._currency = None
        if currency is not None:
            normalized_currency = currency.strip().upper()
            if (
                len(normalized_currency) != 3
                or not normalized_currency.isascii()
                or not normalized_currency.isalpha()
            ):
                raise ValueError("Currency must be a three-letter code")
            self._currency = normalized_currency
        self._pricing_config_version = self._get_pricing_version(
            pricing if pricing is not None else {},
            self._currency,
            pricing_version,
        )
        self._records: deque[LLMCallTelemetryRecord] = deque(
            maxlen=recent_record_limit
        )
        self._latency_samples: deque[float] = deque(maxlen=median_sample_limit)
        self._lock = threading.Lock()
        self._total_calls = 0
        self._successful_calls = 0
        self._total_requests = 0
        self._successful_requests = 0
        self._fallback_attempts = 0
        self._fallback_successes = 0
        self._latency_total = 0.0
        self._provider_model_usage: dict[str, int] = {}
        self._token_totals = {"input": 0, "output": 0, "total": 0}
        self._token_observations = {"input": 0, "output": 0, "total": 0}
        self._estimated_cost_by_currency: dict[str, float] = {}
        self._estimated_cost_calls = 0

    @property
    def pricing_config_version(self) -> str | None:
        return self._pricing_config_version

    @staticmethod
    def _get_pricing_version(
        configured: Mapping[str, Mapping[str, Mapping[str, float]]],
        currency: str | None,
        configured_version: str | None,
    ) -> str | None:
        if not configured:
            return None
        if configured_version is not None:
            version = configured_version.strip()
            if not version:
                raise ValueError("Pricing version cannot be blank")
            return version
        normalized = {
            provider: {
                model: dict(sorted(rates.items()))
                for model, rates in sorted(models.items())
            }
            for provider, models in sorted(configured.items())
        }
        fingerprint = json.dumps(
            {"currency": currency, "pricing": normalized},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(fingerprint).hexdigest()}"

    @staticmethod
    def _parse_pricing(
        configured: Mapping[str, Mapping[str, Mapping[str, float]]],
    ) -> dict[tuple[str, str], ModelPricing]:
        parsed: dict[tuple[str, str], ModelPricing] = {}
        if not isinstance(configured, Mapping):
            raise TypeError("Pricing must be a provider/model mapping")
        for provider, models in configured.items():
            if not isinstance(provider, str) or not provider.strip():
                raise ValueError("Pricing provider names cannot be blank")
            if not isinstance(models, Mapping):
                raise TypeError("Each provider's pricing must map model names")
            for model, rates in models.items():
                if not isinstance(model, str) or not model.strip():
                    raise ValueError("Pricing model names cannot be blank")
                if not isinstance(rates, Mapping):
                    raise TypeError("Each model's pricing must be a rate mapping")
                if set(rates) != {
                    "input_per_million_tokens",
                    "output_per_million_tokens",
                }:
                    raise ValueError(
                        "Pricing requires input_per_million_tokens and "
                        "output_per_million_tokens"
                    )
                parsed[(provider, model)] = ModelPricing(**rates)
        return parsed

    def _estimate_cost(self, attempt: LLMCallTelemetry) -> float | None:
        return self.estimate_cost_for_usage(
            attempt.provider,
            attempt.model,
            attempt.input_token_count,
            attempt.output_token_count,
        )

    def pricing_metadata(self, provider: str, model: str) -> dict[str, object]:
        pricing = self._pricing.get((provider, model))
        return {
            "pricing_config_version": self._pricing_config_version,
            "pricing_currency": self._currency,
            "input_price_per_million_tokens": (
                pricing.input_per_million_tokens if pricing else None
            ),
            "output_price_per_million_tokens": (
                pricing.output_per_million_tokens if pricing else None
            ),
        }

    def estimate_cost_for_usage(
        self,
        provider: str,
        model: str,
        input_token_count: int | None,
        output_token_count: int | None,
    ) -> float | None:
        pricing = self._pricing.get((provider, model))
        if (
            pricing is None
            or input_token_count is None
            or output_token_count is None
        ):
            return None
        estimate = (
            input_token_count * pricing.input_per_million_tokens
            + output_token_count * pricing.output_per_million_tokens
        ) / 1_000_000
        return estimate if math.isfinite(estimate) else None

    def _build_records(
        self,
        attempts: Sequence[LLMCallTelemetry],
    ) -> list[LLMCallTelemetryRecord]:
        if not attempts:
            raise ValueError("At least one provider attempt is required")
        records = []
        for attempt in attempts:
            pricing = self._pricing.get((attempt.provider, attempt.model))
            estimate = self._estimate_cost(attempt)
            records.append(
                LLMCallTelemetryRecord(
                    **attempt.__dict__,
                    estimated_cost=estimate,
                    estimated_cost_currency=(
                        self._currency if estimate is not None else None
                    ),
                    cost_is_estimate=estimate is not None,
                    pricing_config_version=self._pricing_config_version,
                    pricing_currency=self._currency,
                    input_price_per_million_tokens=(
                        pricing.input_per_million_tokens if pricing else None
                    ),
                    output_price_per_million_tokens=(
                        pricing.output_per_million_tokens if pricing else None
                    ),
                )
            )
        return records

    def _aggregate_records(
        self,
        records: Sequence[LLMCallTelemetryRecord],
    ) -> None:
        with self._lock:
            self._total_requests += 1
            self._successful_requests += int(records[-1].request_success)
            self._fallback_attempts += int(records[0].fallback_attempted)
            self._fallback_successes += int(records[0].fallback_succeeded)
            for record in records:
                self._total_calls += 1
                self._successful_calls += int(record.success)
                self._latency_total += record.latency_ms
                self._latency_samples.append(record.latency_ms)
                model_key = f"{record.provider}/{record.model}"
                self._provider_model_usage[model_key] = (
                    self._provider_model_usage.get(model_key, 0) + 1
                )
                for name, value in (
                    ("input", record.input_token_count),
                    ("output", record.output_token_count),
                    ("total", record.total_token_count),
                ):
                    if value is not None:
                        self._token_totals[name] += value
                        self._token_observations[name] += 1
                if record.estimated_cost is not None:
                    currency = record.estimated_cost_currency
                    if currency is not None:
                        self._estimated_cost_by_currency[currency] = (
                            self._estimated_cost_by_currency.get(currency, 0.0)
                            + record.estimated_cost
                        )
                    self._estimated_cost_calls += 1
                self._records.append(record)

    def record_request(self, attempts: Sequence[LLMCallTelemetry]) -> None:
        self._aggregate_records(self._build_records(attempts))

    def get_recent_records(self) -> tuple[LLMCallTelemetryRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def get_summary(self) -> LLMTelemetrySummary:
        with self._lock:
            total_calls = self._total_calls
            total_requests = self._total_requests
            fallback_attempts = self._fallback_attempts
            estimated_cost_calls = self._estimated_cost_calls
            cost_by_currency = dict(self._estimated_cost_by_currency)
            has_single_cost_currency = len(cost_by_currency) == 1
            cost_currency = (
                next(iter(cost_by_currency)) if has_single_cost_currency else None
            )
            return LLMTelemetrySummary(
                total_calls=total_calls,
                successful_calls=self._successful_calls,
                failed_calls=total_calls - self._successful_calls,
                success_rate=(
                    self._successful_calls / total_calls if total_calls else None
                ),
                average_latency_ms=(
                    self._latency_total / total_calls if total_calls else None
                ),
                median_latency_ms=(
                    statistics.median(self._latency_samples)
                    if self._latency_samples
                    else None
                ),
                provider_model_usage=dict(self._provider_model_usage),
                total_requests=total_requests,
                successful_requests=self._successful_requests,
                failed_requests=total_requests - self._successful_requests,
                fallback_attempts=fallback_attempts,
                fallback_successes=self._fallback_successes,
                fallback_success_rate=(
                    self._fallback_successes / fallback_attempts
                    if fallback_attempts
                    else None
                ),
                total_input_tokens=(
                    self._token_totals["input"]
                    if self._token_observations["input"]
                    else None
                ),
                input_token_observations=self._token_observations["input"],
                total_output_tokens=(
                    self._token_totals["output"]
                    if self._token_observations["output"]
                    else None
                ),
                output_token_observations=self._token_observations["output"],
                total_tokens=(
                    self._token_totals["total"]
                    if self._token_observations["total"]
                    else None
                ),
                total_token_observations=self._token_observations["total"],
                estimated_total_cost=(
                    cost_by_currency[cost_currency]
                    if has_single_cost_currency and cost_currency is not None
                    else None
                ),
                estimated_cost_currency=cost_currency,
                estimated_cost_calls=estimated_cost_calls,
                estimated_cost_coverage=(
                    estimated_cost_calls / total_calls if total_calls else None
                ),
                estimated_total_cost_is_partial=(
                    estimated_cost_calls < total_calls if total_calls else None
                ),
                estimated_cost_by_currency=cost_by_currency,
            )


class JsonlLLMTelemetryService(InMemoryLLMTelemetryService):
    """Thread-safe, append-only JSONL telemetry for a single application process."""

    def __init__(
        self,
        pricing: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None,
        currency: str | None = None,
        *,
        pricing_version: str | None = None,
        storage_path: str | Path | None = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        recent_record_limit: int = 1000,
        median_sample_limit: int = 10000,
        load_existing: bool = True,
    ) -> None:
        if max_bytes < 1 or backup_count < 1:
            raise ValueError("Telemetry rotation limits must be positive")
        super().__init__(
            pricing,
            currency,
            pricing_version=pricing_version,
            recent_record_limit=recent_record_limit,
            median_sample_limit=median_sample_limit,
        )
        configured_path = Path(storage_path) if storage_path is not None else None
        if configured_path is None:
            self._storage_path = _DEFAULT_TELEMETRY_PATH
        elif configured_path.is_absolute():
            self._storage_path = configured_path
        else:
            self._storage_path = Path(__file__).resolve().parents[2] / configured_path
        self._storage_path = self._storage_path.resolve()
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._path_lock = _lock_for_path(self._storage_path)
        if load_existing:
            self._load_existing()

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    @property
    def pricing_config_version(self) -> str | None:
        return self._pricing_config_version

    @staticmethod
    def _record_from_json(value: object) -> LLMCallTelemetryRecord:
        if not isinstance(value, dict):
            raise ValueError("Telemetry attempt must be an object")
        required = set(LLMCallTelemetryRecord.__dataclass_fields__)
        if not required.issubset(value):
            raise ValueError("Telemetry attempt is incomplete")

        data = dict(value)
        data["request_timestamp"] = datetime.fromisoformat(
            data["request_timestamp"]
        )
        data["completion_timestamp"] = datetime.fromisoformat(
            data["completion_timestamp"]
        )
        for field_name in (
            "latency_ms",
            "estimated_cost",
            "input_price_per_million_tokens",
            "output_price_per_million_tokens",
        ):
            field_value = data[field_name]
            if field_value is not None and (
                isinstance(field_value, bool)
                or not isinstance(field_value, (int, float))
                or not math.isfinite(field_value)
                or field_value < 0
            ):
                raise ValueError("Telemetry numeric field is invalid")
        for field_name in (
            "input_token_count",
            "output_token_count",
            "total_token_count",
        ):
            field_value = data[field_name]
            if field_value is not None and (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value < 0
            ):
                raise ValueError("Telemetry token count is invalid")
        for field_name in (
            "success",
            "cost_is_estimate",
            "is_fallback_attempt",
            "fallback_attempted",
            "fallback_succeeded",
            "request_success",
        ):
            if not isinstance(data[field_name], bool):
                raise ValueError("Telemetry boolean field is invalid")
        if (
            not isinstance(data["attempt_number"], int)
            or isinstance(data["attempt_number"], bool)
            or data["attempt_number"] < 1
        ):
            raise ValueError("Telemetry attempt number is invalid")
        if not all(
            isinstance(data[field_name], str) and data[field_name]
            for field_name in (
                "provider",
                "model",
                "primary_provider",
                "primary_model",
                "final_provider",
                "final_model",
            )
        ):
            raise ValueError("Telemetry provider/model is invalid")
        for field_name in (
            "error_category",
            "request_id",
            "estimated_cost_currency",
            "pricing_config_version",
            "pricing_currency",
        ):
            if data[field_name] is not None and not isinstance(
                data[field_name], str
            ):
                raise ValueError("Telemetry text field is invalid")
        if data["estimated_cost"] is not None and not data["cost_is_estimate"]:
            raise ValueError("Telemetry cost must be marked as an estimate")
        return LLMCallTelemetryRecord(**data)

    def _event_records(self, line: str) -> list[LLMCallTelemetryRecord]:
        event = json.loads(line)
        if (
            not isinstance(event, dict)
            or event.get("schema_version") != _TELEMETRY_SCHEMA_VERSION
            or not isinstance(event.get("attempts"), list)
            or not event["attempts"]
        ):
            raise ValueError("Telemetry event is invalid")
        return [self._record_from_json(item) for item in event["attempts"]]

    def _history_paths(self) -> list[Path]:
        backups = [
            Path(f"{self._storage_path}.{index}")
            for index in range(self._backup_count, 0, -1)
        ]
        return [path for path in backups if path.is_file()] + [
            self._storage_path
        ]

    def _load_existing(self) -> None:
        with self._path_lock:
            for history_path in self._history_paths():
                try:
                    with history_path.open(
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    ) as file:
                        for line_number, line in enumerate(file, start=1):
                            if not line.strip():
                                continue
                            try:
                                records = self._event_records(line)
                            except (
                                json.JSONDecodeError,
                                KeyError,
                                TypeError,
                                ValueError,
                                OverflowError,
                            ):
                                logger.warning(
                                    "Skipping malformed LLM telemetry record: "
                                    "file=%s line=%d",
                                    history_path,
                                    line_number,
                                )
                                continue
                            self._aggregate_records(records)
                except (OSError, UnicodeError) as exc:
                    logger.error(
                        "Unable to read LLM telemetry: file=%s error_type=%s",
                        history_path,
                        type(exc).__name__,
                    )

    def _rotate_if_needed(self, next_record_size: int) -> None:
        try:
            current_size = self._storage_path.stat().st_size
        except FileNotFoundError:
            return
        if current_size + next_record_size <= self._max_bytes:
            return
        oldest = Path(f"{self._storage_path}.{self._backup_count}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self._backup_count - 1, 0, -1):
            source = Path(f"{self._storage_path}.{index}")
            if source.exists():
                os.replace(source, Path(f"{self._storage_path}.{index + 1}"))
        if self._storage_path.exists():
            os.replace(self._storage_path, Path(f"{self._storage_path}.1"))

    def _append_records(
        self,
        records: Sequence[LLMCallTelemetryRecord],
    ) -> None:
        event = {
            "schema_version": _TELEMETRY_SCHEMA_VERSION,
            "attempts": [
                {
                    **asdict(record),
                    "request_timestamp": record.request_timestamp.isoformat(),
                    "completion_timestamp": record.completion_timestamp.isoformat(),
                }
                for record in records
            ],
        }
        payload = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with self._path_lock:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._rotate_if_needed(len(payload))
            flags = os.O_CREAT | os.O_APPEND | os.O_RDWR
            descriptor = os.open(self._storage_path, flags, 0o600)
            try:
                if os.name != "nt":
                    os.chmod(self._storage_path, stat.S_IRUSR | stat.S_IWUSR)
                current_size = os.fstat(descriptor).st_size
                if current_size:
                    os.lseek(descriptor, -1, os.SEEK_END)
                    if os.read(descriptor, 1) != b"\n":
                        os.write(descriptor, b"\n")
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("Unable to append complete telemetry record")
                    remaining = remaining[written:]
            finally:
                os.close(descriptor)

    def record_request(self, attempts: Sequence[LLMCallTelemetry]) -> None:
        records = self._build_records(attempts)
        try:
            self._append_records(records)
        except (OSError, ValueError, TypeError) as exc:
            logger.error(
                "Unable to persist LLM telemetry: error_type=%s",
                type(exc).__name__,
            )
        self._aggregate_records(records)


def get_persisted_telemetry_summary() -> LLMTelemetrySummary:
    """Return a read-only summary loaded from the retained JSONL history."""
    service = JsonlLLMTelemetryService(
        settings.LLM_PRICING,
        settings.LLM_PRICING_CURRENCY,
        pricing_version=settings.LLM_PRICING_VERSION,
        storage_path=settings.LLM_TELEMETRY_PATH,
        max_bytes=settings.LLM_TELEMETRY_MAX_BYTES,
        backup_count=settings.LLM_TELEMETRY_BACKUP_COUNT,
    )
    return service.get_summary()


_default_telemetry_service: JsonlLLMTelemetryService | None = None
_default_telemetry_lock = threading.Lock()


def get_default_telemetry_service() -> JsonlLLMTelemetryService:
    global _default_telemetry_service
    if _default_telemetry_service is None:
        with _default_telemetry_lock:
            if _default_telemetry_service is None:
                _default_telemetry_service = JsonlLLMTelemetryService(
                    settings.LLM_PRICING,
                    settings.LLM_PRICING_CURRENCY,
                    pricing_version=settings.LLM_PRICING_VERSION,
                    storage_path=settings.LLM_TELEMETRY_PATH,
                    max_bytes=settings.LLM_TELEMETRY_MAX_BYTES,
                    backup_count=settings.LLM_TELEMETRY_BACKUP_COUNT,
                )
    return _default_telemetry_service
