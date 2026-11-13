from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.organization import Organization
from app.models.project import Project
from app.services.analytics_service import AnalyticsService


def test_execution_status_classification_preserves_blank_missing_and_other():
    cases = [
        (" PASSED ", "passed"),
        ("Failed", "failed"),
        (" error ", "error"),
        ("Skipped", "skipped"),
        ("custom-status", "other"),
        (None, "missing"),
        (" \t ", "blank"),
        (42, "other"),
    ]

    for raw_status, expected in cases:
        assert AnalyticsService.classify_execution_status(raw_status) == expected


def test_execution_status_counts_normalize_and_keep_unknown_buckets_separate():
    counts = AnalyticsService.execution_status_counts(
        [
            (" PASSED ", 2),
            ("passed", 1),
            ("custom", 3),
            (None, 1),
            ("", 2),
        ]
    )

    assert counts == {
        "passed": 3,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "other": 3,
        "missing": 1,
        "blank": 2,
    }


def test_test_case_statistics_count_all_review_states_and_unexpected_values():
    result = AnalyticsService.test_case_statistics(
        [
            (" Positive ", "HIGH", "approved", 2),
            ("negative", "low", "draft", 1),
            ("boundary", "critical", "rejected", 3),
            ("unexpected", None, "  ", 2),
        ]
    )

    assert result == {
        "total_cases": 8,
        "category_counts": {
            "positive": 2,
            "negative": 1,
            "boundary": 3,
            "edge": 0,
            "other": 2,
            "missing": 0,
            "blank": 0,
        },
        "priority_counts": {
            "low": 1,
            "medium": 0,
            "high": 2,
            "critical": 3,
            "other": 0,
            "missing": 2,
            "blank": 0,
        },
        "review_status_counts": {
            "draft": 1,
            "approved": 2,
            "rejected": 3,
            "other": 0,
            "missing": 0,
            "blank": 2,
        },
    }


def test_test_case_statistics_distinguish_missing_and_blank_values():
    result = AnalyticsService.test_case_statistics(
        [
            (None, None, None, 1),
            (" ", "\t", "  ", 2),
        ]
    )

    for metric in ("category_counts", "priority_counts", "review_status_counts"):
        assert result[metric]["missing"] == 1
        assert result[metric]["blank"] == 2
        assert result[metric]["other"] == 0


def test_empty_test_case_statistics_are_measured_zero_counts():
    result = AnalyticsService.test_case_statistics([])

    assert result["total_cases"] == 0
    assert sum(result["category_counts"].values()) == 0
    assert sum(result["priority_counts"].values()) == 0
    assert sum(result["review_status_counts"].values()) == 0
    for metric in ("category_counts", "priority_counts", "review_status_counts"):
        assert result[metric]["missing"] == 0
        assert result[metric]["blank"] == 0


def test_requirement_traceability_deduplicates_links_and_separates_inferred():
    requirements = [
        (1, "explicit", 10),
        (2, "explicit", 10),
        (3, "inferred", 10),
    ]
    links = [
        (1, 21, "draft", 10, 10),
        (1, 22, " APPROVED ", 10, 10),
        (1, 22, "approved", 10, 10),
        (2, 23, "rejected", 10, 10),
        (2, 24, "approved", 10, 11),
        (3, 25, "approved", 10, 10),
    ]

    result = AnalyticsService.requirement_traceability(requirements, links)

    assert result == {
        "explicit_requirement_count": 2,
        "inferred_requirement_count": 1,
        "explicit_requirements_with_any_case_link": 2,
        "explicit_requirements_with_approved_case_link": 1,
        "unlinked_explicit_requirement_count": 0,
        "any_case_link_rate": 100,
        "approved_case_link_rate": 50,
    }


def test_requirement_traceability_rates_are_unavailable_without_explicit_requirements():
    result = AnalyticsService.requirement_traceability(
        [(1, "inferred", 10)],
        [(1, 20, "approved", 10, 10)],
    )

    assert result["explicit_requirement_count"] == 0
    assert result["inferred_requirement_count"] == 1
    assert result["any_case_link_rate"] is None
    assert result["approved_case_link_rate"] is None


def test_duration_statistics_ignore_invalid_values_and_report_coverage():
    result = AnalyticsService.duration_statistics(
        [100, 0, None, -1, float("inf"), float("nan"), True, 300]
    )

    assert result == {
        "average_ms": 133.33,
        "median_ms": 100,
        "observed_run_count": 3,
        "unavailable_run_count": 5,
    }


def test_duration_statistics_are_unavailable_when_no_valid_samples():
    result = AnalyticsService.duration_statistics([None, -10, float("inf")])

    assert result == {
        "average_ms": None,
        "median_ms": None,
        "observed_run_count": 0,
        "unavailable_run_count": 3,
    }


def test_time_window_requires_both_bounds_and_aware_utc_offsets():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="provided together"):
        AnalyticsService.resolve_time_window(start, None)
    with pytest.raises(ValueError, match="UTC offset"):
        AnalyticsService.resolve_time_window(
            datetime(2026, 11, 1),
            datetime(2026, 11, 2),
        )


def test_time_window_validates_order_and_maximum_range():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="later"):
        AnalyticsService.resolve_time_window(start, start)
    with pytest.raises(ValueError, match="366 days"):
        AnalyticsService.resolve_time_window(
            start,
            start + timedelta(days=367),
        )


def test_default_trend_window_is_trailing_30_days():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)

    start, end = AnalyticsService.resolve_time_window(
        None,
        None,
        default_days=30,
        now=now,
    )

    assert start == now - timedelta(days=30)
    assert end == now


def test_daily_trend_uses_half_open_utc_range_and_zero_fills_intersecting_days():
    start = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    end = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    rows = [
        ("passed", datetime(2026, 11, 1, 11)),  # excluded before from
        (" passed ", datetime(2026, 11, 1, 12)),  # included at from
        ("failed", datetime(2026, 11, 2, 8)),
        (None, datetime(2026, 11, 3, 12)),  # excluded at to
    ]

    buckets = AnalyticsService.build_execution_trend(rows, start, end, "day")

    assert len(buckets) == 3
    assert buckets[0]["start"] == "2026-11-01T12:00:00+00:00"
    assert buckets[0]["end"] == "2026-11-02T00:00:00+00:00"
    assert buckets[0]["run_count"] == 1
    assert buckets[0]["pass_rate"] == 100
    assert buckets[1]["status_counts"]["failed"] == 1
    assert buckets[1]["pass_rate"] == 0
    assert buckets[2]["run_count"] == 0
    assert buckets[2]["pass_rate"] is None


def test_week_trends_start_on_monday_and_month_trends_follow_calendar_months():
    week_start = datetime(2026, 11, 11, tzinfo=timezone.utc)
    week_end = datetime(2026, 11, 15, tzinfo=timezone.utc)
    weekly = AnalyticsService.build_execution_trend(
        [],
        week_start,
        week_end,
        "week",
    )
    assert len(weekly) == 1
    assert weekly[0]["start"] == "2026-11-11T00:00:00+00:00"
    assert weekly[0]["end"] == "2026-11-15T00:00:00+00:00"

    month_start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    month_end = datetime(2026, 3, 1, tzinfo=timezone.utc)
    monthly = AnalyticsService.build_execution_trend(
        [],
        month_start,
        month_end,
        "month",
    )
    assert [bucket["start"] for bucket in monthly] == [
        "2026-01-15T00:00:00+00:00",
        "2026-02-01T00:00:00+00:00",
    ]
    assert [bucket["end"] for bucket in monthly] == [
        "2026-02-01T00:00:00+00:00",
        "2026-03-01T00:00:00+00:00",
    ]


def test_trend_pass_rate_excludes_error_skipped_other_missing_and_blank():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, tzinfo=timezone.utc)
    rows = [
        ("passed", datetime(2026, 11, 1, 1)),
        ("failed", datetime(2026, 11, 1, 2)),
        ("error", datetime(2026, 11, 1, 3)),
        ("skipped", datetime(2026, 11, 1, 4)),
        ("other", datetime(2026, 11, 1, 5)),
        (None, datetime(2026, 11, 1, 6)),
        (" ", datetime(2026, 11, 1, 7)),
    ]

    bucket = AnalyticsService.build_execution_trend(rows, start, end, "day")[0]

    assert bucket["run_count"] == 7
    assert bucket["status_counts"]["passed"] == 1
    assert bucket["status_counts"]["failed"] == 1
    assert bucket["status_counts"]["error"] == 1
    assert bucket["status_counts"]["skipped"] == 1
    assert bucket["status_counts"]["other"] == 1
    assert bucket["status_counts"]["missing"] == 1
    assert bucket["status_counts"]["blank"] == 1
    assert bucket["pass_rate"] == 50


class _AuthorizationQuery:
    def __init__(self, project):
        self.project = project
        self.joined = False
        self.filters = []

    def join(self, model):
        self.joined = model is Organization
        return self

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def first(self):
        return self.project


class _AuthorizationDB:
    def __init__(self, project):
        self.query_result = _AuthorizationQuery(project)
        self.queried_model = None

    def query(self, model):
        self.queried_model = model
        return self.query_result


@pytest.mark.parametrize(
    "method_name,kwargs",
    [
        ("get_test_case_statistics", {}),
        ("get_requirement_traceability", {}),
        ("get_execution_analytics", {}),
        ("get_execution_trends", {}),
    ],
)
def test_analytics_service_enforces_project_owner_scope_before_aggregation(
    method_name,
    kwargs,
):
    db = _AuthorizationDB(project=None)

    with pytest.raises(ValueError, match="Project not found"):
        getattr(AnalyticsService(db), method_name)(
            project_id=9,
            current_user_id=3,
            **kwargs,
        )

    assert db.queried_model is Project
    assert db.query_result.joined
    assert len(db.query_result.filters) == 2


def test_trend_bucket_rejects_invalid_values():
    with pytest.raises(ValueError, match="Bucket"):
        AnalyticsService.build_execution_trend(
            [],
            datetime(2026, 11, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 2, tzinfo=timezone.utc),
            "quarter",
        )
