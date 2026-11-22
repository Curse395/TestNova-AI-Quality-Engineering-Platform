from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_activity import ProjecActivity
from app.models.project_requirement import ProjectRequirement
from app.models.test_case import TestCase
from app.models.test_case_generation_run import TestCaseGenerationRun
from app.models.test_case_requirement import TestCaseRequirement
from app.services.analytics_service import AnalyticsService
from app.services.recomendation_service import RecommendationService


class DashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.recommendation_service = RecommendationService(db)

    def _test_generation_metrics(self, project_ids: list[int]) -> dict[str, Any]:
        if not project_ids:
            workspace = {
                "explicit_requirements": 0,
                "linked_explicit_requirements": 0,
                "requirement_case_coverage_percent": None,
                "persisted_ai_generated_test_cases": 0,
                "generation_runs_with_saved_cases": 0,
            }
            return {"workspace": workspace, "by_project": {}}

        explicit_counts = dict(
            self.db.query(
                ProjectRequirement.project_id,
                func.count(ProjectRequirement.id),
            )
            .filter(
                ProjectRequirement.project_id.in_(project_ids),
                ProjectRequirement.classification == "explicit",
            )
            .group_by(ProjectRequirement.project_id)
            .all()
        )
        linked_counts = dict(
            self.db.query(
                ProjectRequirement.project_id,
                func.count(func.distinct(ProjectRequirement.id)),
            )
            .join(
                TestCaseRequirement,
                TestCaseRequirement.requirement_id == ProjectRequirement.id,
            )
            .join(
                TestCase,
                (TestCase.id == TestCaseRequirement.test_case_id)
                & (TestCase.project_id == ProjectRequirement.project_id),
            )
            .filter(
                ProjectRequirement.project_id.in_(project_ids),
                ProjectRequirement.classification == "explicit",
            )
            .group_by(ProjectRequirement.project_id)
            .all()
        )
        generated_case_counts = dict(
            self.db.query(
                TestCase.project_id,
                func.count(func.distinct(TestCase.id)),
            )
            .join(
                TestCaseGenerationRun,
                TestCaseGenerationRun.id == TestCase.generation_run_id,
            )
            .filter(
                TestCase.project_id.in_(project_ids),
                TestCaseGenerationRun.project_id == TestCase.project_id,
            )
            .group_by(TestCase.project_id)
            .all()
        )
        generation_run_rows = (
            self.db.query(
                TestCaseGenerationRun.project_id,
                TestCaseGenerationRun.id,
                TestCaseGenerationRun.workflow_run_id,
                TestCaseGenerationRun.status,
            )
            .join(
                TestCase,
                (TestCase.generation_run_id == TestCaseGenerationRun.id)
                & (TestCase.project_id == TestCaseGenerationRun.project_id),
            )
            .filter(TestCaseGenerationRun.project_id.in_(project_ids))
            .all()
        )

        run_keys_by_project: dict[int, set[tuple[str, int]]] = {
            project_id: set() for project_id in project_ids
        }
        for project_id, generation_run_id, workflow_run_id, status in generation_run_rows:
            if status not in {"completed", "partial"}:
                continue
            key = (
                ("workflow", workflow_run_id)
                if workflow_run_id is not None
                else ("generation_run", generation_run_id)
            )
            run_keys_by_project.setdefault(project_id, set()).add(key)

        by_project: dict[str, dict[str, Any]] = {}
        for project_id in project_ids:
            explicit = int(explicit_counts.get(project_id, 0))
            linked = int(linked_counts.get(project_id, 0))
            by_project[str(project_id)] = {
                "explicit_requirements": explicit,
                "linked_explicit_requirements": linked,
                "requirement_case_coverage_percent": AnalyticsService.coverage_percentage(
                    linked,
                    explicit,
                ),
                "persisted_ai_generated_test_cases": int(
                    generated_case_counts.get(project_id, 0)
                ),
                "generation_runs_with_saved_cases": len(
                    run_keys_by_project.get(project_id, set())
                ),
            }

        explicit_total = sum(item["explicit_requirements"] for item in by_project.values())
        linked_total = sum(item["linked_explicit_requirements"] for item in by_project.values())
        workspace = {
            "explicit_requirements": explicit_total,
            "linked_explicit_requirements": linked_total,
            "requirement_case_coverage_percent": AnalyticsService.coverage_percentage(
                linked_total,
                explicit_total,
            ),
            "persisted_ai_generated_test_cases": sum(
                item["persisted_ai_generated_test_cases"]
                for item in by_project.values()
            ),
            "generation_runs_with_saved_cases": sum(
                item["generation_runs_with_saved_cases"]
                for item in by_project.values()
            ),
        }
        return {"workspace": workspace, "by_project": by_project}

    def get_dashboard(self, current_user_id: int) -> dict[str, Any]:
        project_rows = (
            self.db.query(Project.id, Project.name)
            .join(Organization, Project.organitzation_id == Organization.id)
            .filter(Organization.owner_id == current_user_id)
            .all()
        )
        project_ids = [project_id for project_id, _ in project_rows]
        test_generation_metrics = self._test_generation_metrics(project_ids)

        document_counts: dict[int, int] = {}
        documents_with_chunks_counts: dict[int, int] = {}
        chunk_counts: dict[int, int] = {}
        embedding_counts: dict[int, int] = {}
        if project_ids:
            document_counts = dict(
                self.db.query(Document.project_id, func.count(Document.id))
                .filter(Document.project_id.in_(project_ids))
                .group_by(Document.project_id)
                .all()
            )
            documents_with_chunks_counts = dict(
                self.db.query(
                    Document.project_id,
                    func.count(func.distinct(Document.id)),
                )
                .join(DocumentChunk, DocumentChunk.document_id == Document.id)
                .filter(Document.project_id.in_(project_ids))
                .group_by(Document.project_id)
                .all()
            )
            chunk_counts = dict(
                self.db.query(Document.project_id, func.count(DocumentChunk.id))
                .join(DocumentChunk, DocumentChunk.document_id == Document.id)
                .filter(Document.project_id.in_(project_ids))
                .group_by(Document.project_id)
                .all()
            )
            embedding_counts = dict(
                self.db.query(Document.project_id, func.count(DocumentEmbedding.id))
                .join(DocumentChunk, DocumentChunk.document_id == Document.id)
                .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
                .filter(Document.project_id.in_(project_ids))
                .group_by(Document.project_id)
                .all()
            )

        active_projects = []
        for project_id, project_name in project_rows:
            documents = int(document_counts.get(project_id, 0))
            documents_with_chunks = int(documents_with_chunks_counts.get(project_id, 0))
            chunks = int(chunk_counts.get(project_id, 0))
            embeddings = int(embedding_counts.get(project_id, 0))
            active_projects.append(
                {
                    "id": project_id,
                    "name": project_name,
                    "documents": documents,
                    "documents_with_chunks": documents_with_chunks,
                    "chunks": chunks,
                    "embeddings": embeddings,
                    "document_chunk_coverage": AnalyticsService.coverage_percentage(
                        documents_with_chunks,
                        documents,
                    ),
                    "embedding_coverage": AnalyticsService.coverage_percentage(
                        embeddings,
                        chunks,
                    ),
                }
            )

        total_documents = sum(document_counts.values())
        documents_with_chunks = sum(documents_with_chunks_counts.values())
        total_chunks = sum(chunk_counts.values())
        total_embeddings = sum(embedding_counts.values())

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
            "test_generation_metrics": test_generation_metrics,
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
