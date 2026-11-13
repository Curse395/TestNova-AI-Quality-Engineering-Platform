from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authorization import get_owned_project
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.project_schema import ProjectCreate, ProjectUpdate, ProjectResponse


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_project(self, current_user: User, data: ProjectCreate) -> ProjectResponse:
        organization_query = self.db.query(Organization).filter(
            Organization.owner_id == current_user.id
        )
        if data.organization_id is not None:
            organization_query = organization_query.filter(
                Organization.id == data.organization_id
            )
        organization = organization_query.order_by(Organization.id.asc()).first()
        if not organization:
            raise ValueError("Organization not found")

        project = Project(
            name=data.name,
            description=data.description,
            organitzation_id=organization.id,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            organization_id=project.organitzation_id,
        )

    def list_projects(self, current_user: User) -> list[ProjectResponse]:
        organizations = self.db.query(Organization).filter(Organization.owner_id == current_user.id).all()
        organization_ids = [organization.id for organization in organizations]
        if not organization_ids:
            return []

        projects = (
            self.db.query(Project)
            .filter(Project.organitzation_id.in_(organization_ids))
            .order_by(Project.created_at.desc())
            .all()
        )
        return [
            ProjectResponse(
                id=project.id,
                name=project.name,
                description=project.description,
                organization_id=project.organitzation_id,
            )
            for project in projects
        ]

    def update_project(self, current_user: User, project_id: int, data: ProjectUpdate) -> ProjectResponse:
        project = get_owned_project(self.db, project_id, current_user.id)
        if not project:
            raise ValueError("Project not found")

        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description

        self.db.commit()
        self.db.refresh(project)
        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            organization_id=project.organitzation_id,
        )

    def delete_project(self, current_user: User, project_id: int) -> None:
        project = get_owned_project(self.db, project_id, current_user.id)
        if not project:
            raise ValueError("Project not found")

        self.db.delete(project)
        self.db.commit()

    def get_dashboard(self, current_user: User, project_id: int) -> dict[str, object]:
        project = get_owned_project(self.db, project_id, current_user.id)
        if not project:
            raise ValueError("Project not found")

        documents_query = self.db.query(Document).filter(
            Document.project_id == project.id
        )
        document_count = documents_query.count()
        failed_documents = documents_query.filter(
            Document.processing_status == "failed"
        ).count()
        pending_documents = documents_query.filter(
            Document.processing_status.notin_(("completed", "failed"))
        ).count()
        total_chunks = (
            self.db.query(DocumentChunk)
            .join(Document)
            .filter(Document.project_id == project.id)
            .count()
        )
        total_embeddings = (
            self.db.query(func.count(DocumentEmbedding.id))
            .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.project_id == project.id)
            .scalar()
        ) or 0

        if document_count == 0:
            status = "no_documents"
            summary = "Upload a document to begin building project knowledge."
        elif failed_documents:
            status = "failed"
            summary = (
                f"{failed_documents} of {document_count} documents failed processing."
            )
        elif pending_documents:
            status = "processing"
            summary = (
                f"{pending_documents} of {document_count} documents are not processed."
            )
        elif total_chunks == 0:
            status = "no_chunks"
            summary = "Documents are processed, but no chunks are available."
        elif total_embeddings < total_chunks:
            status = "embedding"
            summary = (
                f"{total_embeddings} of {total_chunks} chunks have embeddings."
            )
        else:
            status = "ready"
            summary = (
                f"{document_count} documents and {total_chunks} embedded chunks are ready."
            )

        latest_upload = documents_query.with_entities(
            func.max(Document.uploaded_at)
        ).scalar()
        return {
            "project_id": project.id,
            "project_name": project.name,
            "status": status,
            "summary": summary,
            "document_count": document_count,
            "chunk_count": total_chunks,
            "embedding_count": total_embeddings,
            "updated_at": (
                latest_upload.isoformat()
                if latest_upload
                else project.created_at.isoformat() if project.created_at else None
            ),
        }
