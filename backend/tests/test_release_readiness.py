from types import SimpleNamespace
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import analytics as analytics_api
from app.database.connection import Base
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase as CaseModel
from app.models.test_execution import TestExecutionRun as ExecutionRunModel
from app.models.user import User
from app.schemas.release_readiness_schema import ReleaseReadinessResponse
from app.services.analytics_service import AnalyticsService
from app.services.project_intelligence_service import ProjectIntelligenceService
from app.services.release_readiness_service import ReleaseReadinessService


def _evidence(
    *,
    total_runs=1,
    passed=1,
    failed=0,
    errors=0,
    approved=1,
    drafts=0,
    rejected=0,
    explicit=1,
    approved_linked=1,
    any_linked=1,
    unlinked=0,
    risks=None,
    workflows=None,
):
    status_counts = {
        "passed": passed,
        "failed": failed,
        "error": errors,
        "skipped": 0,
        "other": 0,
        "missing": 0,
        "blank": 0,
    }
    return {
        "test_cases": {
            "total_cases": approved + drafts + rejected,
            "review_status_counts": {
                "draft": drafts,
                "approved": approved,
                "rejected": rejected,
                "other": 0,
                "missing": 0,
                "blank": 0,
            },
            "category_counts": {"positive": 1, "negative": 0, "boundary": 0, "edge": 0},
            "priority_counts": {"low": 0, "medium": 0, "high": 1, "critical": 0},
        },
        "traceability": {
            "explicit_requirement_count": explicit,
            "inferred_requirement_count": 8,
            "explicit_requirements_with_any_case_link": any_linked,
            "explicit_requirements_with_approved_case_link": approved_linked,
            "unlinked_explicit_requirement_count": unlinked,
            "any_case_link_rate": 100.0 if explicit else None,
            "approved_case_link_rate": 100.0 if explicit else None,
        },
        "executions": {
            "total_runs": total_runs,
            "status_counts": status_counts,
            "duration": {
                "average_ms": None,
                "median_ms": None,
                "observed_run_count": 0,
                "unavailable_run_count": total_runs,
            },
        },
        "risks": risks if risks is not None else {
            "risk_count": 0,
            "risks": [],
            "risk_task_window_truncated": False,
            "evidence_available": True,
            "unavailable_reason": None,
        },
        "workflows": workflows if workflows is not None else {
            "workflow_count": 0,
            "workflows": [],
            "workflow_status_counts": {
                "pending": 0,
                "running": 0,
                "completed": 0,
                "partially_completed": 0,
                "failed": 0,
                "other": 0,
            },
        },
    }


def _assess(evidence, *, recent=None):
    return ReleaseReadinessService.build_assessment(
        test_cases=evidence["test_cases"],
        traceability=evidence["traceability"],
        executions=evidence["executions"],
        risks=evidence["risks"],
        workflows=evidence["workflows"],
        recent_executions=recent or [],
    )


def test_empty_project_is_insufficient_and_empty_history_is_not_a_pass_rate():
    evidence = _evidence(total_runs=0, passed=0, approved=0, explicit=0, approved_linked=0, any_linked=0)

    result = _assess(evidence)

    assert result["assessment"]["state"] == "insufficient_evidence"
    assert any(item["id"] == "execution_history_missing" for item in result["concerns"])
    assert any(item["id"] == "no_approved_cases" for item in result["concerns"])
    assert any(item["id"] == "explicit_requirements_missing" for item in result["concerns"])
    assert AnalyticsService.pass_rate(0, 0) is None


def test_missing_core_analytics_produce_insufficient_evidence_not_success():
    evidence = _evidence()
    evidence["executions"] = None

    result = _assess(evidence)

    assert result["assessment"]["state"] == "insufficient_evidence"
    assert "Required project analytics are unavailable" in result["assessment"]["reasons"][0]


@pytest.mark.parametrize(
    ("failed", "errors", "expected_concern"),
    [(1, 0, "failed_executions"), (0, 1, "execution_errors"), (2, 1, "failed_executions")],
)
def test_observed_failed_or_errored_runs_block_review(failed, errors, expected_concern):
    evidence = _evidence(passed=1, failed=failed, errors=errors, total_runs=1 + failed + errors)
    recent = [
        {"id": 13, "status_class": "failed"},
        {"id": 14, "status_class": "error"},
    ]

    result = _assess(evidence, recent=recent)

    assert result["assessment"]["state"] == "blocked"
    assert any(item["id"] == expected_concern for item in result["concerns"])
    assert "risk score" not in str(result).lower()
    if failed and errors:
        assert any(item["id"] == "execution_errors" for item in result["concerns"])


def test_unapproved_cases_and_unlinked_explicit_requirements_need_attention():
    evidence = _evidence(
        approved=1,
        drafts=2,
        rejected=1,
        explicit=3,
        approved_linked=1,
        any_linked=2,
        unlinked=1,
    )

    result = _assess(evidence)
    concern_ids = {item["id"] for item in result["concerns"]}

    assert result["assessment"]["state"] == "attention_required"
    assert "unapproved_test_cases" in concern_ids
    assert "requirements_without_approved_case_link" in concern_ids
    assert evidence["traceability"]["inferred_requirement_count"] == 8
    assert "8" not in next(
        item["explanation"]
        for item in result["concerns"]
        if item["id"] == "requirements_without_approved_case_link"
    )


def test_high_inferred_risk_requires_attention_and_keeps_evidence_attribution():
    evidence = _evidence(risks={
        "risk_count": 1,
        "risks": [{
            "id": "risk-4",
            "kind": "ai_inferred",
            "severity": "high",
            "description": "A high risk is assessed.",
            "evidence_references": [{"id": "document:2:chunk:3"}],
        }],
        "risk_task_window_truncated": False,
        "evidence_available": True,
    })

    result = _assess(evidence)
    concern = next(item for item in result["concerns"] if item["id"] == "risk:risk-4")

    assert result["assessment"]["state"] == "attention_required"
    assert concern["attention"] == "high"
    assert concern["evidence_ids"] == ["document:2:chunk:3"]
    assert "probability" not in concern["explanation"]


def test_failed_workflow_is_attention_not_a_test_execution_blocker():
    evidence = _evidence(workflows={
        "workflow_count": 1,
        "workflows": [{"id": 5, "status": "failed"}],
        "workflow_status_counts": {"failed": 1, "partially_completed": 0},
    })

    result = _assess(evidence)

    assert result["assessment"]["state"] == "attention_required"
    assert next(item for item in result["concerns"] if item["id"] == "workflow_failures")["evidence_ids"] == ["workflow:5"]


def test_missing_persisted_risk_evidence_is_not_presented_as_no_risk():
    evidence = _evidence(risks={
        "risk_count": 0,
        "risks": [],
        "risk_task_window_truncated": False,
        "evidence_available": False,
        "unavailable_reason": "No persisted risk assessments exist.",
    })

    result = _assess(evidence)

    assert result["assessment"]["state"] == "attention_required"
    concern = next(item for item in result["concerns"] if item["id"] == "risk_evidence_unavailable")
    assert concern["attention"] == "medium"
    assert "not proof of no risk" in concern["next_action"]


def test_unknown_execution_statuses_are_not_passes_and_attention_is_required():
    evidence = _evidence()
    evidence["executions"]["total_runs"] = 2
    evidence["executions"]["status_counts"]["missing"] = 1
    evidence["executions"]["status_counts"]["passed"] = 1

    result = _assess(evidence, recent=[{"id": 22, "status_class": "missing"}])

    assert result["assessment"]["state"] == "attention_required"
    concern = next(item for item in result["concerns"] if item["id"] == "indeterminate_execution_statuses")
    assert concern["evidence_ids"] == ["execution_run:22"]


def test_positive_complete_evidence_is_ready_for_review_not_production_ready():
    result = _assess(_evidence())

    assert result["assessment"]["state"] == "ready_for_review"
    assert "not a production-readiness determination" in result["assessment"]["explanation"]
    assert result["concerns"] == []


def test_same_evidence_produces_same_state_reasons_and_concerns():
    evidence = _evidence(failed=1, total_runs=2)

    first = _assess(evidence)
    second = _assess(evidence)

    assert first == second


def test_ai_summary_cannot_override_observed_execution_blocker():
    evidence = _evidence(failed=1, total_runs=2)
    evidence["risks"]["ai_summary"] = {
        "status": "available",
        "summary": "Ready for release",
    }

    result = _assess(evidence, recent=[{"id": 13, "status_class": "failed"}])

    assert result["assessment"]["state"] == "blocked"


def test_missing_status_counts_do_not_become_zero_or_ready():
    evidence = _evidence()
    del evidence["executions"]["status_counts"]["missing"]

    result = _assess(evidence)

    assert result["assessment"]["state"] == "insufficient_evidence"
    assert any("execution status counts" in reason for reason in result["assessment"]["reasons"])


class _OwnershipQuery:
    def __init__(self, owned):
        self.owned = owned
        self.joins = []
        self.filters = []

    def join(self, model, onclause=None):
        self.joins.append((model, onclause))
        return self

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def first(self):
        return SimpleNamespace(id=4) if self.owned else None


class _OwnershipDB:
    def __init__(self, owned):
        self.owned = owned
        self.queried_model = None
        self.query_result = None

    def query(self, model):
        self.queried_model = model
        self.query_result = _OwnershipQuery(self.owned)
        return self.query_result


@pytest.mark.parametrize("owned", [True, False])
def test_project_intelligence_ownership_gate_checks_owner_scoped_project(owned):
    db = _OwnershipDB(owned)
    service = ProjectIntelligenceService(db)

    if owned:
        service.require_owned_project(4, 9)
    else:
        with pytest.raises(ValueError, match="Project not found"):
            service.require_owned_project(4, 9)

    assert db.queried_model is Project
    assert len(db.query_result.joins) == 1
    joined_model, onclause = db.query_result.joins[0]
    assert joined_model is Organization
    assert onclause.compare(Project.organitzation_id == Organization.id)
    assert len(db.query_result.filters) == 2


def test_release_service_rejects_non_positive_project_id_before_database_access():
    db = _OwnershipDB(owned=True)

    with pytest.raises(ValueError, match="positive integer"):
        ReleaseReadinessService(db).get_project_release_readiness(0, 9)

    assert db.queried_model is None


def test_release_service_rejects_another_users_project_before_analytics_queries():
    db = _OwnershipDB(owned=False)

    with pytest.raises(ValueError, match="Project not found"):
        ReleaseReadinessService(db).get_project_release_readiness(4, 10)

    assert db.queried_model is Project


def test_execution_health_counts_only_persisted_runs_for_the_selected_project():
    # Import all model modules before metadata creation so SQLAlchemy can resolve
    # the application's existing relationships in this isolated SQLite database.
    import importlib
    import pkgutil
    import app.models

    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(name="Owner", email="release-owner@example.test", password_hash="test")
        organization = Organization(name="Release test org", owner=user)
        session.add(organization)
        session.flush()
        selected_project = Project(name="Selected", organitzation_id=organization.id)
        other_project = Project(name="Other", organitzation_id=organization.id)
        empty_project = Project(name="No runs", organitzation_id=organization.id)
        session.add_all([selected_project, other_project, empty_project])
        session.flush()

        cases = []
        for project, title in (
            (selected_project, "Selected passed"),
            (selected_project, "Selected failed"),
            (other_project, "Other project run"),
        ):
            case = CaseModel(
                project_id=project.id,
                created_by_user_id=user.id,
                title=title,
                description="Persisted fixture case",
                test_type="functional",
                category="positive",
                priority="medium",
                severity="medium",
                steps=[{"action": "Run", "expected_result": "Pass"}],
                expected_result="Pass",
                review_status="approved",
            )
            session.add(case)
            cases.append(case)
        session.flush()
        session.add_all([
            ExecutionRunModel(
                project_id=selected_project.id,
                test_case_id=cases[0].id,
                executed_by_user_id=user.id,
                status="passed",
                duration_ms=10,
                assertions=[],
            ),
            ExecutionRunModel(
                project_id=selected_project.id,
                test_case_id=cases[1].id,
                executed_by_user_id=user.id,
                status="failed",
                duration_ms=None,
                assertions=[],
            ),
            ExecutionRunModel(
                project_id=other_project.id,
                test_case_id=cases[2].id,
                executed_by_user_id=user.id,
                status="passed",
                duration_ms=4,
                assertions=[],
            ),
        ])
        session.commit()

        selected = AnalyticsService(session).get_execution_analytics(
            selected_project.id,
            user.id,
        )
        empty = AnalyticsService(session).get_execution_analytics(
            empty_project.id,
            user.id,
        )

    assert selected["total_runs"] == 2
    assert selected["status_counts"]["passed"] == 1
    assert selected["status_counts"]["failed"] == 1
    assert selected["duration"]["average_ms"] == 10
    assert empty["total_runs"] == 0
    assert empty["duration"]["average_ms"] is None
    assert empty["duration"]["median_ms"] is None


def test_release_service_composes_existing_analytics_into_valid_response(monkeypatch):
    evidence = _evidence(total_runs=2, passed=2)
    evidence["executions"]["duration"] = {
        "average_ms": 14.0,
        "median_ms": 14.0,
        "observed_run_count": 2,
        "unavailable_run_count": 0,
    }
    evidence["test_cases"]["project_id"] = 4
    evidence["traceability"]["project_id"] = 4
    evidence["executions"]["project_id"] = 4
    ownership_calls = []
    workflow = {
        "project_id": 4,
        "snapshot_only": True,
        "workflow_count": 1,
        "workflows": [{
            "id": 8,
            "status": "completed",
            "workflow_type": "test_generation",
            "duration_ms": 125,
            "task_count": 1,
            "failed_task_count": 0,
            "retried_task_count": 1,
            "tasks": [{"attempts": [{"attempt_number": 1}, {"attempt_number": 2}]}],
        }],
    }

    class _Analytics:
        classify_execution_status = staticmethod(AnalyticsService.classify_execution_status)
        pass_rate = staticmethod(AnalyticsService.pass_rate)

        def __init__(self, _db):
            pass

        def get_test_case_statistics(self, project_id, user_id):
            assert (project_id, user_id) == (4, 9)
            return evidence["test_cases"]

        def get_requirement_traceability(self, project_id, user_id):
            assert (project_id, user_id) == (4, 9)
            return evidence["traceability"]

        def get_execution_analytics(self, project_id, user_id):
            assert (project_id, user_id) == (4, 9)
            return evidence["executions"]

        def get_execution_trends(self, project_id, user_id, bucket):
            assert (project_id, user_id, bucket) == (4, 9, "day")
            return {"from": "2026-10-15T00:00:00+00:00", "to": "2026-11-14T00:00:00+00:00", "bucket": "day", "buckets": []}

    class _Intelligence:
        def __init__(self, _db):
            pass

        def require_owned_project(self, project_id, user_id):
            ownership_calls.append((project_id, user_id))

        def get_project_risks(self, project_id, user_id):
            assert (project_id, user_id) == (4, 9)
            return evidence["risks"]

        def get_workflow_monitoring(self, project_id, user_id, limit):
            assert (project_id, user_id, limit) == (4, 9, 20)
            return workflow

    class _Query:
        def filter(self, *_conditions):
            return self

        def order_by(self, *_expressions):
            return self

        def limit(self, _limit):
            return self

        def all(self):
            return [(31, "passed", datetime(2026, 11, 13, 12))]

        def one(self):
            timestamp = datetime(2026, 11, 13, 12)
            return timestamp, timestamp, 2

    class _DB:
        def query(self, *_entities):
            return _Query()

    monkeypatch.setattr("app.services.release_readiness_service.AnalyticsService", _Analytics)
    monkeypatch.setattr("app.services.release_readiness_service.ProjectIntelligenceService", _Intelligence)

    result = ReleaseReadinessService(_DB()).get_project_release_readiness(4, 9)
    validated = ReleaseReadinessResponse.model_validate(result)

    assert ownership_calls == [(4, 9)]
    assert validated.assessment.state == "ready_for_review"
    assert validated.metrics["executions"]["pass_rate"] == 100.0
    assert validated.metrics["executions"]["recent_runs"][0]["id"] == 31
    assert validated.metrics["executions"]["time_range"]["observed_run_count"] == 2
    assert validated.metrics["workflows"]["workflow_status_counts"]["completed"] == 1
    assert validated.metrics["workflows"]["attempt_count"] == 2


def test_release_readiness_route_returns_response_and_passes_authenticated_owner(monkeypatch):
    evidence = _evidence()
    decision = _assess(evidence)
    response = {
        "project_id": 4,
        **decision,
        "metrics": {},
        "limitations": [],
    }
    calls = []

    class _Service:
        def __init__(self, db):
            assert db == "offline-db"

        def get_project_release_readiness(self, project_id, current_user_id):
            calls.append((project_id, current_user_id))
            return response

    monkeypatch.setattr(analytics_api, "ReleaseReadinessService", _Service)

    result = analytics_api.get_project_release_readiness(
        project_id=4,
        current_user=SimpleNamespace(id=9),
        db="offline-db",
    )

    assert result == response
    assert calls == [(4, 9)]
    ReleaseReadinessResponse.model_validate(result)


def test_release_readiness_route_maps_non_owner_to_not_found(monkeypatch):
    class _Service:
        def __init__(self, _db):
            pass

        def get_project_release_readiness(self, **_kwargs):
            raise ValueError("Project not found")

    monkeypatch.setattr(analytics_api, "ReleaseReadinessService", _Service)

    with pytest.raises(HTTPException) as error:
        analytics_api.get_project_release_readiness(
            project_id=4,
            current_user=SimpleNamespace(id=10),
            db=None,
        )

    assert error.value.status_code == 404


def test_release_readiness_route_maps_invalid_project_id_to_validation_error(monkeypatch):
    class _Service:
        def __init__(self, _db):
            pass

        def get_project_release_readiness(self, **_kwargs):
            raise ValueError("Project ID must be a positive integer.")

    monkeypatch.setattr(analytics_api, "ReleaseReadinessService", _Service)

    with pytest.raises(HTTPException) as error:
        analytics_api.get_project_release_readiness(
            project_id=0,
            current_user=SimpleNamespace(id=9),
            db=None,
        )

    assert error.value.status_code == 422
