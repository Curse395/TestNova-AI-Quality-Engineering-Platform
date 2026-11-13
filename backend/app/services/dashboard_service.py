from typing import Any

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.project_activity import ProjecActivity
from app.services.analytics_service import AnalyticsService
from app.services.recomendation_service import RecommendationService


class DashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.analytics_service = AnalyticsService(db)
        self.recommendation_service = RecommendationService(db)

    def get_dashboard(self, current_user_id: int) -> dict[str, Any]:
        organizations = (
            self.db.query(Organization)
            .filter(Organization.owner_id == current_user_id)
            .all()
        )

        active_projects = []
        project_ids = []
        total_documents = 0
        documents_with_chunks = 0
        total_chunks = 0
        total_embeddings = 0

        for organization in organizations:
            projects = (
                self.db.query(Project)
                .filter(Project.organitzation_id == organization.id)
                .all()
            )
            for project in projects:
                metrics = self.analytics_service.get_project_overview(
                    project_id=project.id,
                    current_user_id=current_user_id,
                )
                project_ids.append(project.id)
                active_projects.append(
                    {
                        "id": project.id,
                        "name": project.name,
                        "documents": metrics["documents"],
                        "documents_with_chunks": metrics["documents_with_chunks"],
                        "chunks": metrics["chunks"],
                        "embeddings": metrics["embeddings"],
                        "document_chunk_coverage": metrics[
                            "document_chunk_coverage"
                        ],
                        "embedding_coverage": metrics["embedding_coverage"],
                    }
                )
                total_documents += metrics["documents"]
                documents_with_chunks += metrics["documents_with_chunks"]
                total_chunks += metrics["chunks"]
                total_embeddings += metrics["embeddings"]

        overview = {
            "total_projects": len(active_projects),
            "total_documents": total_documents,
            "documents_with_chunks": documents_with_chunks,
            "total_chunks": total_chunks,
            "total_embeddings": total_embeddings,
            "document_chunk_coverage": AnalyticsService.coverage_percentage(
                documents_with_chunks,
                total_documents,
            ),
            "embedding_coverage": AnalyticsService.coverage_percentage(
                total_embeddings,
                total_chunks,
            ),
        }

        activities = []
        if project_ids:
            activities = (
                self.db.query(ProjecActivity)
                .filter(ProjecActivity.project_id.in_(project_ids))
                .order_by(ProjecActivity.created_at.asc())
                .all()
            )
        knowledge_history = [
            {
                "date": activity.created_at.isoformat(),
                "documents": activity.documents,
                "chunks": activity.chunks,
                "embeddings": activity.embeddings,
            }
            for activity in activities
        ]

        dashboard = {
            "active_projects": active_projects,
            "overview": overview,
            "test_generation": {
                "coverage_uplift": None,
                "flake_reduction": None,
                "time_saved_minutes": None,
            },
            "assistant": {"suggestions": []},
            "knowledge_history": knowledge_history,
        }
        dashboard["assistant"] = {
            "suggestions": self.recommendation_service.get_workspace_recomendations(
                dashboard
            )
        }
        return dashboard

    def get_dashboard_insights(self, current_user_id: int) -> dict[str, Any]:
        dashboard = self.get_dashboard(current_user_id)
        overview = dashboard["overview"]
        total_documents = overview["total_documents"]
        documents_with_chunks = overview["documents_with_chunks"]
        total_chunks = overview["total_chunks"]
        total_embeddings = overview["total_embeddings"]

        if total_documents == 0:
            summary = "No documents have been uploaded to this workspace."
        else:
            summary = (
                f"{documents_with_chunks} of {total_documents} documents have chunks. "
            )
            if total_chunks == 0:
                summary += "Embedding coverage is unavailable because no chunks exist."
            else:
                summary += (
                    f"{total_embeddings} of {total_chunks} chunks have embeddings."
                )

        issues = []
        if total_documents > documents_with_chunks:
            issues.append(
                {
                    "title": "Documents without chunks",
                    "description": (
                        f"{total_documents - documents_with_chunks} documents "
                        "do not have any chunks."
                    ),
                    "severity": "Medium",
                }
            )
        if total_chunks > total_embeddings:
            issues.append(
                {
                    "title": "Chunks without embeddings",
                    "description": (
                        f"{total_chunks - total_embeddings} chunks do not have "
                        "embeddings."
                    ),
                    "severity": "High",
                }
            )

        recommendations = [
            suggestion["description"]
            for suggestion in dashboard["assistant"]["suggestions"]
        ]
        return {
            "summary": summary,
            "issues": issues,
            "recommendations": recommendations,
        }
