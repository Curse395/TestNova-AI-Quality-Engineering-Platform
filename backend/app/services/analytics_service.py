import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_requirement import ProjectRequirement
from app.models.test_case import TestCase
from app.models.test_case_requirement import TestCaseRequirement
from app.models.test_execution import TestExecutionRun

EXECUTION_STATUS_KEYS = (
    "passed",
    "failed",
    "error",
    "skipped",
    "other",
    "missing",
    "blank",
)
TEST_CASE_CATEGORIES = ("positive", "negative", "boundary", "edge")
TEST_CASE_PRIORITIES = ("low", "medium", "high", "critical")
REVIEW_STATUSES = ("draft", "approved", "rejected")
TREND_BUCKETS = ("day", "week", "month")
MAX_ANALYTICS_RANGE = timedelta(days=366)
TREND_DEFAULT_RANGE = timedelta(days=30)


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def coverage_percentage(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round(numerator / denominator * 100, 2)

    @staticmethod
    def pass_rate(passed: int, failed: int) -> float | None:
        denominator = passed + failed
        if denominator <= 0:
            return None
        return round(passed / denominator * 100, 2)

    @staticmethod
    def classify_execution_status(status: object) -> str:
        if status is None:
            return "missing"
        if not isinstance(status, str):
            return "other"
        normalized = status.strip().lower()
        if not normalized:
            return "blank"
        if normalized in {"passed", "failed", "error", "skipped"}:
            return normalized
        return "other"

    @staticmethod
    def execution_status_counts(status_counts: Iterable[tuple[object, int]]) -> dict[str, int]:
        counts = {key: 0 for key in EXECUTION_STATUS_KEYS}
        for status, count in status_counts:
            counts[AnalyticsService.classify_execution_status(status)] += int(count)
        return counts

    @staticmethod
    def duration_statistics(values: Iterable[object]) -> dict[str, int | float | None]:
        valid = []
        unavailable_count = 0
        for value in values:
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                valid.append(float(value))
            else:
                unavailable_count += 1
        return {
            "average_ms": round(statistics.fmean(valid), 2) if valid else None,
            "median_ms": round(statistics.median(valid), 2) if valid else None,
            "observed_run_count": len(valid),
            "unavailable_run_count": unavailable_count,
        }

    @staticmethod
    def test_case_statistics(
        grouped_rows: Iterable[tuple[object, object, object, int]],
    ) -> dict[str, Any]:
        category_counts = {value: 0 for value in TEST_CASE_CATEGORIES}
        category_counts.update({"other": 0, "missing": 0, "blank": 0})
        priority_counts = {value: 0 for value in TEST_CASE_PRIORITIES}
        priority_counts.update({"other": 0, "missing": 0, "blank": 0})
        review_counts = {value: 0 for value in REVIEW_STATUSES}
        review_counts.update({"other": 0, "missing": 0, "blank": 0})
        total_cases = 0

        for category, priority, review_status, count in grouped_rows:
            count = int(count)
            total_cases += count
            for value, counts in (
                (category, category_counts),
                (priority, priority_counts),
                (review_status, review_counts),
            ):
                if value is None:
                    bucket = "missing"
                elif isinstance(value, str) and not value.strip():
                    bucket = "blank"
                else:
                    normalized = value.strip().lower() if isinstance(value, str) else None
                    bucket = (
                        normalized
                        if normalized in counts and normalized not in {"other", "missing", "blank"}
                        else "other"
                    )
                counts[bucket] += count

        return {
            "total_cases": total_cases,
            "category_counts": category_counts,
            "priority_counts": priority_counts,
            "review_status_counts": review_counts,
        }

    @staticmethod
    def requirement_traceability(
        requirements: Iterable[tuple[int, str, int]],
        links: Iterable[tuple[int, int, str | None, int, int]],
    ) -> dict[str, int | float | None]:
        explicit_ids = set()
        inferred_count = 0
        for requirement_id, classification, _project_id in requirements:
            normalized = (
                classification.strip().lower()
                if isinstance(classification, str)
                else ""
            )
            if normalized == "explicit":
                explicit_ids.add(requirement_id)
            elif normalized == "inferred":
                inferred_count += 1

        linked_ids: set[int] = set()
        approved_linked_ids: set[int] = set()
        for requirement_id, _case_id, review_status, requirement_project_id, case_project_id in links:
            if (
                requirement_id not in explicit_ids
                or requirement_project_id != case_project_id
            ):
                continue
            linked_ids.add(requirement_id)
            if (
                isinstance(review_status, str)
                and review_status.strip().lower() == "approved"
            ):
                approved_linked_ids.add(requirement_id)

        denominator = len(explicit_ids)
        return {
            "explicit_requirement_count": denominator,
            "inferred_requirement_count": inferred_count,
            "explicit_requirements_with_any_case_link": len(linked_ids),
            "explicit_requirements_with_approved_case_link": len(
                approved_linked_ids
            ),
            "unlinked_explicit_requirement_count": denominator - len(linked_ids),
            "any_case_link_rate": AnalyticsService.coverage_percentage(
                len(linked_ids),
                denominator,
            ),
            "approved_case_link_rate": AnalyticsService.coverage_percentage(
                len(approved_linked_ids),
                denominator,
            ),
        }

    @staticmethod
    def resolve_time_window(
        start: datetime | None,
        end: datetime | None,
        *,
        default_days: int | None = None,
        now: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        if (start is None) != (end is None):
            raise ValueError("Both 'from' and 'to' must be provided together.")

        if start is None:
            if default_days is None:
                raise ValueError("Both 'from' and 'to' are required.")
            resolved_end = now or datetime.now(timezone.utc)
            if resolved_end.tzinfo is None or resolved_end.utcoffset() is None:
                raise ValueError("Analytics timestamps must include a UTC offset.")
            resolved_end = resolved_end.astimezone(timezone.utc)
            resolved_start = resolved_end - timedelta(days=default_days)
        else:
            if (
                start.tzinfo is None
                or start.utcoffset() is None
                or end is None
                or end.tzinfo is None
                or end.utcoffset() is None
            ):
                raise ValueError("Analytics timestamps must include a UTC offset.")
            resolved_start = start.astimezone(timezone.utc)
            resolved_end = end.astimezone(timezone.utc)

        if resolved_end <= resolved_start:
            raise ValueError("'to' must be later than 'from'.")
        if resolved_end - resolved_start > MAX_ANALYTICS_RANGE:
            raise ValueError("Analytics date range cannot exceed 366 days.")
        return resolved_start, resolved_end

    @staticmethod
    def _bucket_start(value: datetime, bucket: str) -> datetime:
        value = value.astimezone(timezone.utc)
        if bucket == "day":
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        if bucket == "week":
            day = value.replace(hour=0, minute=0, second=0, microsecond=0)
            return day - timedelta(days=day.weekday())
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_bucket(value: datetime, bucket: str) -> datetime:
        if bucket == "month":
            if value.month == 12:
                return value.replace(year=value.year + 1, month=1)
            return value.replace(month=value.month + 1)
        return value + (timedelta(days=7) if bucket == "week" else timedelta(days=1))

    @classmethod
    def build_execution_trend(
        cls,
        rows: Iterable[tuple[object, datetime]],
        start: datetime,
        end: datetime,
        bucket: str,
    ) -> list[dict[str, Any]]:
        if bucket not in TREND_BUCKETS:
            raise ValueError("Bucket must be one of: day, week, month.")
        start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        first_bucket = cls._bucket_start(start_utc, bucket)
        buckets: dict[datetime, dict[str, int]] = {}
        cursor = first_bucket
        while cursor < end_utc:
            buckets[cursor] = {key: 0 for key in EXECUTION_STATUS_KEYS}
            cursor = cls._next_bucket(cursor, bucket)

        for status, created_at in rows:
            timestamp = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at.astimezone(timezone.utc)
            if not start_utc <= timestamp < end_utc:
                continue
            key = cls._bucket_start(timestamp, bucket)
            if key in buckets:
                buckets[key][cls.classify_execution_status(status)] += 1

        result = []
        for bucket_start, status_counts in buckets.items():
            bucket_end = cls._next_bucket(bucket_start, bucket)
            interval_start = max(bucket_start, start_utc)
            interval_end = min(bucket_end, end_utc)
            passed = status_counts["passed"]
            failed = status_counts["failed"]
            result.append(
                {
                    "start": interval_start.isoformat(),
                    "end": interval_end.isoformat(),
                    "run_count": sum(status_counts.values()),
                    "status_counts": status_counts,
                    "pass_rate": AnalyticsService.pass_rate(passed, failed),
                }
            )
        return result

    def _require_owned_project(self, project_id: int, current_user_id: int) -> None:
        project = (
            self.db.query(Project)
            .join(Organization)
            .filter(
                Project.id == project_id,
                Organization.owner_id == current_user_id,
            )
            .first()
        )
        if project is None:
            raise ValueError("Project not found")

    def get_project_overview(
        self,
        project_id: int,
        current_user_id: int,
    ) -> dict[str, int | float | None]:
        self._require_owned_project(project_id, current_user_id)

        total_documents = (
            self.db.query(func.count(Document.id))
            .filter(Document.project_id == project_id)
            .scalar()
            or 0
        )
        documents_with_chunks = (
            self.db.query(func.count(func.distinct(DocumentChunk.document_id)))
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.project_id == project_id)
            .scalar()
            or 0
        )
        total_chunks = (
            self.db.query(func.count(DocumentChunk.id))
            .join(Document)
            .filter(Document.project_id == project_id)
            .scalar()
            or 0
        )
        total_embeddings = (
            self.db.query(func.count(DocumentEmbedding.id))
            .join(DocumentChunk)
            .join(Document)
            .filter(Document.project_id == project_id)
            .scalar()
            or 0
        )

        return {
            "project_id": project_id,
            "documents": total_documents,
            "documents_with_chunks": documents_with_chunks,
            "chunks": total_chunks,
            "embeddings": total_embeddings,
            "document_chunk_coverage": self.coverage_percentage(
                documents_with_chunks,
                total_documents,
            ),
            "embedding_coverage": self.coverage_percentage(
                total_embeddings,
                total_chunks,
            ),
        }

    def get_document_statistics(
        self,
        current_user_id: int,
        project_id: int,
    ) -> list[dict[str, int | str]]:
        self._require_owned_project(project_id, current_user_id)

        documents = (
            self.db.query(Document)
            .filter(Document.project_id == project_id)
            .all()
        )

        statistics = []
        for document in documents:
            chunk_count = (
                self.db.query(func.count(DocumentChunk.id))
                .filter(DocumentChunk.document_id == document.id)
                .scalar()
                or 0
            )
            embedding_count = (
                self.db.query(func.count(DocumentEmbedding.id))
                .join(
                    DocumentChunk,
                    DocumentEmbedding.chunk_id == DocumentChunk.id,
                )
                .filter(DocumentChunk.document_id == document.id)
                .scalar()
                or 0
            )
            statistics.append(
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "chunks": chunk_count,
                    "embeddings": embedding_count,
                }
            )

        return statistics

    def get_test_case_statistics(
        self,
        project_id: int,
        current_user_id: int,
    ) -> dict[str, Any]:
        self._require_owned_project(project_id, current_user_id)
        grouped_rows = (
            self.db.query(
                TestCase.category,
                TestCase.priority,
                TestCase.review_status,
                func.count(TestCase.id),
            )
            .filter(TestCase.project_id == project_id)
            .group_by(
                TestCase.category,
                TestCase.priority,
                TestCase.review_status,
            )
            .all()
        )
        return {
            "project_id": project_id,
            **self.test_case_statistics(grouped_rows),
        }

    def get_requirement_traceability(
        self,
        project_id: int,
        current_user_id: int,
    ) -> dict[str, Any]:
        self._require_owned_project(project_id, current_user_id)
        requirements = (
            self.db.query(
                ProjectRequirement.id,
                ProjectRequirement.classification,
                ProjectRequirement.project_id,
            )
            .filter(ProjectRequirement.project_id == project_id)
            .all()
        )
        requirement_ids = [row[0] for row in requirements]
        links = []
        if requirement_ids:
            links = (
                self.db.query(
                    TestCaseRequirement.requirement_id,
                    TestCaseRequirement.test_case_id,
                    TestCase.review_status,
                    ProjectRequirement.project_id,
                    TestCase.project_id,
                )
                .join(
                    ProjectRequirement,
                    ProjectRequirement.id == TestCaseRequirement.requirement_id,
                )
                .join(TestCase, TestCase.id == TestCaseRequirement.test_case_id)
                .filter(
                    ProjectRequirement.project_id == project_id,
                    TestCase.project_id == project_id,
                    TestCaseRequirement.requirement_id.in_(requirement_ids),
                )
                .all()
            )
        return {
            "project_id": project_id,
            "traceability_note": (
                "Requirement links indicate traceability only; they do not prove "
                "that a requirement is fully tested."
            ),
            **self.requirement_traceability(requirements, links),
        }

    def _execution_query(
        self,
        project_id: int,
        start: datetime | None,
        end: datetime | None,
    ):
        query = self.db.query(TestExecutionRun).filter(
            TestExecutionRun.project_id == project_id
        )
        if start is not None and end is not None:
            start_naive = start.astimezone(timezone.utc).replace(tzinfo=None)
            end_naive = end.astimezone(timezone.utc).replace(tzinfo=None)
            query = query.filter(
                TestExecutionRun.created_at >= start_naive,
                TestExecutionRun.created_at < end_naive,
            )
        return query

    def get_execution_analytics(
        self,
        project_id: int,
        current_user_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        self._require_owned_project(project_id, current_user_id)
        if (start is None) != (end is None):
            raise ValueError("Both 'from' and 'to' must be provided together.")
        if start is not None and end is not None:
            start, end = self.resolve_time_window(start, end)

        query = self._execution_query(project_id, start, end)
        grouped_statuses = (
            query.with_entities(TestExecutionRun.status, func.count(TestExecutionRun.id))
            .group_by(TestExecutionRun.status)
            .all()
        )
        durations = query.with_entities(TestExecutionRun.duration_ms).all()
        counts = self.execution_status_counts(grouped_statuses)
        return {
            "project_id": project_id,
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "total_runs": sum(counts.values()),
            "status_counts": counts,
            "duration": self.duration_statistics(row[0] for row in durations),
        }

    def get_execution_trends(
        self,
        project_id: int,
        current_user_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
        bucket: str = "day",
    ) -> dict[str, Any]:
        self._require_owned_project(project_id, current_user_id)
        if bucket not in TREND_BUCKETS:
            raise ValueError("Bucket must be one of: day, week, month.")
        start, end = self.resolve_time_window(
            start,
            end,
            default_days=TREND_DEFAULT_RANGE.days,
        )
        rows = (
            self._execution_query(project_id, start, end)
            .with_entities(TestExecutionRun.status, TestExecutionRun.created_at)
            .order_by(TestExecutionRun.created_at.asc(), TestExecutionRun.id.asc())
            .all()
        )
        return {
            "project_id": project_id,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "bucket": bucket,
            "buckets": self.build_execution_trend(rows, start, end, bucket),
        }
