from datetime import datetime
from types import SimpleNamespace

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

    def all(self):
        return self.rows


class FakeDashboardDB:
    def __init__(self, activity_rows):
        self.activity_rows = activity_rows

    def query(self, model):
        if model.__name__ == "Organization":
            return FakeQuery([SimpleNamespace(id=10)])
        if model.__name__ == "Project":
            return FakeQuery([SimpleNamespace(id=20, name="Project A")])
        if model.__name__ == "ProjecActivity":
            return FakeQuery(self.activity_rows)
        raise AssertionError(f"Unexpected dashboard query model: {model}")


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


def test_dashboard_aggregates_shared_project_metrics_and_labels_history():
    project_metrics = {
        "documents": 4,
        "documents_with_chunks": 2,
        "chunks": 4,
        "embeddings": 3,
        "document_chunk_coverage": 50,
        "embedding_coverage": 75,
    }
    activity = SimpleNamespace(
        created_at=datetime(2026, 11, 13),
        documents=4,
        chunks=4,
        embeddings=3,
    )
    service = DashboardService(FakeDashboardDB([activity]))
    service.analytics_service = SimpleNamespace(
        get_project_overview=lambda **_kwargs: project_metrics,
    )

    dashboard = service.get_dashboard(current_user_id=7)

    assert dashboard["overview"]["document_chunk_coverage"] == 50
    assert dashboard["overview"]["embedding_coverage"] == 75
    assert dashboard["active_projects"][0]["embedding_coverage"] == 75
    assert dashboard["knowledge_history"] == [
        {
            "date": "2026-11-13T00:00:00",
            "documents": 4,
            "chunks": 4,
            "embeddings": 3,
        }
    ]
    assert "performance_trend" not in dashboard
    assert "quality_center" not in dashboard
