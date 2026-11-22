from datetime import datetime
import importlib
import pkgutil
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models
from app.database.connection import Base
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_requirement import ProjectRequirement
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_generation_run import TestCaseGenerationRun as GenerationRunModel
from app.models.test_case_requirement import TestCaseRequirement
from app.models.test_execution import TestExecutionRun as ExecutionRunModel
from app.models.user import User
from app.models.workflow_run import WorkflowRun
from app.services.analytics_service import AnalyticsService
from app.services.dashboard_service import DashboardService
from app.services.recomendation_service import RecommendationService


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_conditions):
        return self

    def order_by(self, *_columns):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def group_by(self, *_columns):
        return self

    def all(self):
        return self.rows


class FakeDashboardDB:
    def __init__(self, query_results):
        self.query_results = query_results
        self.query_count = 0

    def query(self, *_entities):
        result = self.query_results[self.query_count]
        self.query_count += 1
        return FakeQuery(result)


def test_coverage_is_unavailable_without_a_denominator():
    assert AnalyticsService.coverage_percentage(0, 0) is None


def test_coverage_preserves_measured_zero():
    assert AnalyticsService.coverage_percentage(0, 4) == 0


def test_coverage_uses_the_same_percentage_calculation_for_all_scopes():
    assert AnalyticsService.coverage_percentage(1, 4) == 25
    assert AnalyticsService.coverage_percentage(2, 3) == 66.67


def test_recommendations_do_not_claim_release_readiness():
    service = RecommendationService(db=None)
    dashboard = {
        "overview": {
            "total_documents": 0,
            "documents_with_chunks": 0,
            "total_chunks": 0,
            "total_embeddings": 0,
        }
    }

    recommendations = service.get_workspace_recomendations(dashboard)

    assert recommendations[0]["action"] == "upload_documents"
    assert all("release" not in item["title"].lower() for item in recommendations)


def test_dashboard_aggregates_project_metrics_with_a_fixed_number_of_queries():
    activity = SimpleNamespace(
        created_at=datetime(2026, 11, 13),
        documents=4,
        chunks=4,
        embeddings=3,
    )
    db = FakeDashboardDB([
        [(20, "Project A"), (21, "Project B")],
        [(20, 4), (21, 2)],
        [(20, 2), (21, 1)],
        [(20, 5), (21, 7)],
        [
            (20, 101, 500, "completed"),
            (20, 102, 500, "partial"),
            (20, 103, None, "completed"),
            (20, 104, 501, "failed"),
            (21, 105, 502, "completed"),
            (21, 106, 502, "completed"),
        ],
        [(20, 4), (21, 2)],
        [(20, 2), (21, 1)],
        [(20, 4), (21, 2)],
        [(20, 3), (21, 2)],
        [activity],
    ])
    service = DashboardService(db)

    dashboard = service.get_dashboard(current_user_id=7)

    assert db.query_count == 10
    assert dashboard["overview"]["total_projects"] == 2
    assert dashboard["overview"]["document_chunk_coverage"] == 50
    assert dashboard["overview"]["embedding_coverage"] == 83.33
    assert dashboard["active_projects"][0]["documents"] == 4
    assert dashboard["active_projects"][0]["document_chunk_coverage"] == 50
    assert dashboard["active_projects"][0]["embedding_coverage"] == 75
    assert dashboard["active_projects"][1]["documents"] == 2
    assert dashboard["active_projects"][1]["embedding_coverage"] == 100
    assert dashboard["knowledge_history"] == [
        {
            "date": "2026-11-13T00:00:00",
            "documents": 4,
            "chunks": 4,
            "embeddings": 3,
        }
    ]
    assert dashboard["test_generation"]["coverage_uplift"] is None
    assert dashboard["test_generation_metrics"]["by_project"] == {
        "20": {
            "explicit_requirements": 4,
            "linked_explicit_requirements": 2,
            "requirement_case_coverage_percent": 50,
            "persisted_ai_generated_test_cases": 5,
            "generation_runs_with_saved_cases": 2,
        },
        "21": {
            "explicit_requirements": 2,
            "linked_explicit_requirements": 1,
            "requirement_case_coverage_percent": 50,
            "persisted_ai_generated_test_cases": 7,
            "generation_runs_with_saved_cases": 1,
        },
    }
    assert dashboard["test_generation_metrics"]["workspace"] == {
        "explicit_requirements": 6,
        "linked_explicit_requirements": 3,
        "requirement_case_coverage_percent": 50,
        "persisted_ai_generated_test_cases": 12,
        "generation_runs_with_saved_cases": 3,
    }
    assert "performance_trend" not in dashboard
    assert "quality_center" not in dashboard


def test_dashboard_returns_empty_metrics_without_querying_per_project():
    db = FakeDashboardDB([[]])
    service = DashboardService(db)

    dashboard = service.get_dashboard(current_user_id=7)

    assert db.query_count == 1
    assert dashboard["active_projects"] == []
    assert dashboard["overview"]["document_chunk_coverage"] is None
    assert dashboard["overview"]["embedding_coverage"] is None
    assert dashboard["test_generation_metrics"] == {
        "workspace": {
            "explicit_requirements": 0,
            "linked_explicit_requirements": 0,
            "requirement_case_coverage_percent": None,
            "persisted_ai_generated_test_cases": 0,
            "generation_runs_with_saved_cases": 0,
        },
        "by_project": {},
    }


def test_successful_generation_workflows_are_deduplicated_and_failed_attempts_are_excluded():
    service = DashboardService(db=None)
    rows = [
        (20, 301, 900, "completed"),
        (20, 302, 900, "partial"),
        (20, 303, 900, "failed"),
        (20, 304, None, "completed"),
        (20, 305, None, "failed"),
        (21, 306, 901, "completed"),
    ]

    class Query(FakeQuery):
        pass

    class DB:
        def __init__(self, query_rows):
            self.query_rows = iter(query_rows)

        def query(self, *_entities):
            return Query(next(self.query_rows))

    service.db = DB([
        [(20, 1), (21, 4)],
        [(20, 1), (21, 3)],
        [(20, 2), (21, 9)],
        rows,
    ])
    # Explicit requirements, linked requirements, and persisted cases.
    result = service._test_generation_metrics([20])

    assert result["by_project"]["20"]["generation_runs_with_saved_cases"] == 2
    assert result["workspace"]["generation_runs_with_saved_cases"] == 2


def test_dashboard_generation_metrics_use_owned_persisted_data_and_exclude_failed_runs():
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(name="Owner", email="metrics-owner@example.test", password_hash="test")
        other_owner = User(name="Other", email="metrics-other@example.test", password_hash="test")
        owner_org = Organization(name="Owner org", owner=owner)
        other_org = Organization(name="Other org", owner=other_owner)
        session.add_all([owner_org, other_org])
        session.flush()
        owned = Project(name="Owned", organitzation_id=owner_org.id)
        foreign = Project(name="Foreign", organitzation_id=other_org.id)
        session.add_all([owned, foreign])
        session.flush()
        owned_project_id = owned.id
        workflow_one = WorkflowRun(
            project_id=owned.id,
            initiated_by=owner.id,
            workflow_type="test_generation",
            status="partially_completed",
            input_data={},
        )
        workflow_two = WorkflowRun(
            project_id=owned.id,
            initiated_by=owner.id,
            workflow_type="test_generation",
            status="failed",
            input_data={},
        )
        foreign_workflow = WorkflowRun(
            project_id=foreign.id,
            initiated_by=other_owner.id,
            workflow_type="test_generation",
            status="completed",
            input_data={},
        )
        session.add_all([workflow_one, workflow_two, foreign_workflow])
        session.flush()

        requirements = [
            ProjectRequirement(
                project_id=owned.id,
                requirement_key=f"REQ-{number}",
                description=f"Requirement {number}",
                classification="explicit",
                evidence_chunk_ids=[],
            )
            for number in (1, 2)
        ]
        foreign_requirement = ProjectRequirement(
            project_id=foreign.id,
            requirement_key="REQ-FOREIGN",
            description="Foreign requirement",
            classification="explicit",
            evidence_chunk_ids=[],
        )
        session.add_all([*requirements, foreign_requirement])
        session.flush()

        generation_specs = [
            (owned, workflow_one.id, 1, "completed", owner.id),
            (owned, workflow_one.id, 2, "partial", owner.id),
            (owned, None, None, "completed", owner.id),
            (owned, workflow_two.id, 1, "failed", owner.id),
            (foreign, foreign_workflow.id, 1, "completed", other_owner.id),
        ]
        generation_runs = []
        for project, workflow_id, attempt, status, user_id in generation_specs:
            run = GenerationRunModel(
                project_id=project.id,
                created_by_user_id=user_id,
                requirements_prompt="Fixture generation request",
                requested_categories=["positive"],
                requirement_keys=[],
                max_cases=1,
                status=status,
                generated_case_count=1 if status != "failed" else 0,
                final_persisted_count=1,
                workflow_run_id=workflow_id,
                workflow_attempt_number=attempt,
            )
            session.add(run)
            generation_runs.append(run)
        session.flush()

        test_cases = []
        for project, run, user, number in (
            (owned, generation_runs[0], owner, 1),
            (owned, generation_runs[1], owner, 2),
            (owned, generation_runs[2], owner, 3),
            (owned, generation_runs[3], owner, 4),
            (foreign, generation_runs[4], other_owner, 5),
        ):
            case = CaseModel(
                project_id=project.id,
                created_by_user_id=user.id,
                title=f"Case {number}",
                description="Persisted fixture case",
                test_type="functional",
                category="positive",
                priority="medium",
                severity="medium",
                steps=[{"action": "Run", "expected_result": "Pass"}],
                expected_result="Pass",
                review_status="draft",
                generation_run_id=run.id,
            )
            session.add(case)
            test_cases.append(case)
        session.flush()
        session.add_all([
            TestCaseRequirement(test_case_id=test_cases[0].id, requirement_id=requirements[0].id),
            # Deliberately inconsistent cross-project relationship: project scoping
            # must keep this foreign case out of the owned project's numerator.
            TestCaseRequirement(test_case_id=test_cases[4].id, requirement_id=requirements[1].id),
        ])
        session.commit()

        dashboard = DashboardService(session).get_dashboard(owner.id)
        persisted_execution_count = session.query(ExecutionRunModel).count()

    metrics = dashboard["test_generation_metrics"]
    assert [project["name"] for project in dashboard["active_projects"]] == ["Owned"]
    assert metrics["workspace"] == {
        "explicit_requirements": 2,
        "linked_explicit_requirements": 1,
        "requirement_case_coverage_percent": 50,
        "persisted_ai_generated_test_cases": 4,
        "generation_runs_with_saved_cases": 2,
    }
    assert metrics["by_project"][str(owned_project_id)] == metrics["workspace"]
    assert dashboard["test_generation"]["coverage_uplift"] is None
    assert dashboard["test_generation"]["flake_reduction"] is None
    assert dashboard["test_generation"]["time_saved_minutes"] is None
    assert persisted_execution_count == 0
    assert "flake_reduction" not in metrics["workspace"]
