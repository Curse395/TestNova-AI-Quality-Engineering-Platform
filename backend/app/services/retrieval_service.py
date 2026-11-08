import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.model_service import ModelService
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project

logger = logging.getLogger(__name__)

SUPPORTED_SOURCE_TYPES = {
    "document",
    "requirements",
    "bug_report",
    "test_log",
    "technical_document",
    "api_catalogue",
}


class UnsupportedSourceTypeError(ValueError):
    """Raised when retrieval is given an unsupported document source type."""


class RetrievalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search_project_context(
        self,
        current_user_id: int,
        project_id: int,
        query: str,
        limit: int | None = None,
        document_ids: list[int] | None = None,
        source_types: list[str] | None = None,
        min_similarity: float | None = None,
    ) -> list[dict[str, object]]:
        project = (
            self.db.query(Project)
            .join(Organization)
            .filter(
                Project.id == project_id,
                Organization.owner_id == current_user_id,
            )
            .first()
        )
        if not project:
            raise ValueError("Project not found")
        if not query.strip():
            raise ValueError("Search query cannot be empty")

        if document_ids is not None:
            if not document_ids:
                raise ValueError("Select at least one document")

            owned_document_ids = {
                row[0]
                for row in (
                    self.db.query(Document.id)
                    .filter(
                        Document.project_id == project_id,
                        Document.id.in_(document_ids),
                    )
                    .all()
                )
            }
            if owned_document_ids != set(document_ids):
                raise ValueError(
                    "One or more selected documents do not belong to this project"
                )

        normalized_source_types = None
        if source_types is not None:
            normalized_source_types = {source_type.strip().lower() for source_type in source_types}
            if (
                not normalized_source_types
                or not normalized_source_types.issubset(SUPPORTED_SOURCE_TYPES)
            ):
                raise UnsupportedSourceTypeError(
                    "One or more source types are unsupported"
                )

        requested_limit = settings.RETRIEVAL_TOP_K if limit is None else limit
        if requested_limit < 1:
            raise ValueError("Retrieval limit must be at least one")
        result_limit = min(requested_limit, settings.RETRIEVAL_MAX_TOP_K)

        similarity_threshold = (
            settings.RETRIEVAL_MIN_SIMILARITY
            if min_similarity is None
            else min_similarity
        )
        if not math.isfinite(similarity_threshold) or not -1.0 <= similarity_threshold <= 1.0:
            raise ValueError("Minimum similarity must be between -1 and 1")

        query_embedding = ModelService.encode_embedding(query.strip())
        distance = DocumentEmbedding.embedding.cosine_distance(query_embedding)

        results_query = (
            self.db.query(
                DocumentChunk,
                Document,
                DocumentEmbedding.model_name,
                distance.label("distance"),
            )
            .join(
                DocumentEmbedding,
                DocumentEmbedding.chunk_id == DocumentChunk.id,
            )
            .join(
                Document,
                Document.id == DocumentChunk.document_id,
            )
            .filter(
                Document.project_id == project.id,
                DocumentEmbedding.model_name == ModelService.EMBEDDING_MODEL_NAME,
                distance <= 1.0 - similarity_threshold,
            )
        )
        if document_ids is not None:
            results_query = results_query.filter(Document.id.in_(document_ids))
        if normalized_source_types is not None:
            results_query = results_query.filter(
                Document.source_type.in_(normalized_source_types)
            )

        results = (
            results_query
            .order_by(distance.asc())
            .limit(result_limit)
            .all()
        )
        logger.info(
            "Project retrieval complete: project_id=%s matched_chunks=%d",
            project_id,
            len(results),
        )

        retrieved: list[dict[str, object]] = []
        seen_chunk_ids: set[int] = set()
        for chunk, document, model_name, raw_distance in results:
            if not math.isfinite(float(raw_distance)):
                logger.warning(
                    "Skipping retrieval result with invalid cosine distance: "
                    "project_id=%s chunk_id=%s",
                    project_id,
                    chunk.id,
                )
                continue
            if chunk.id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.id)
            source_metadata = chunk.source_metadata or {}
            retrieved.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_name": document.filename,
                    "source_type": document.source_type or "document",
                    "content_type": document.content_type,
                    "uploaded_at": (
                        document.uploaded_at.isoformat()
                        if isinstance(document.uploaded_at, datetime)
                        else document.uploaded_at
                    ),
                    "uploaded_by_user_id": document.uploaded_by_user_id,
                    "processing_status": document.processing_status,
                    "source_metadata": source_metadata,
                    "content": chunk.content,
                    "score": float(raw_distance),
                    "similarity": 1.0 - float(raw_distance),
                    "distance": float(raw_distance),
                    "embedding_model": model_name,
                    "has_embedding": True,
                }
            )
        return retrieved
