from typing import Any

from sqlalchemy.orm import Session


class RecommendationService:
    def __init__(self, db: Session):
        self.db = db

    def get_workspace_recomendations(
        self,
        dashboard: dict[str, Any],
    ) -> list[dict[str, str]]:
        overview = dashboard["overview"]
        total_documents = overview["total_documents"]
        documents_with_chunks = overview["documents_with_chunks"]
        total_chunks = overview["total_chunks"]
        total_embeddings = overview["total_embeddings"]
        recommendations = []

        if total_documents == 0:
            recommendations.append(
                {
                    "title": "Upload project documents",
                    "description": (
                        "Upload documents to begin building the workspace knowledge base."
                    ),
                    "action": "upload_documents",
                    "priority": "Medium",
                }
            )
        elif documents_with_chunks < total_documents:
            recommendations.append(
                {
                    "title": "Process documents",
                    "description": (
                        f"{total_documents - documents_with_chunks} documents "
                        "do not have chunks yet."
                    ),
                    "action": "process_documents",
                    "priority": "High",
                }
            )

        if total_chunks > total_embeddings:
            recommendations.append(
                {
                    "title": "Generate missing embeddings",
                    "description": (
                        f"{total_chunks - total_embeddings} chunks do not have "
                        "embeddings."
                    ),
                    "action": "generate_embeddings",
                    "priority": "High",
                }
            )

        if not recommendations:
            recommendations.append(
                {
                    "title": "Knowledge metrics are up to date",
                    "description": (
                        "All available document chunks have embeddings."
                    ),
                    "action": "generate_tests",
                    "priority": "Low",
                }
            )

        return recommendations
