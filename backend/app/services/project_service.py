from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.shemas.project_schema import ProjectCreate, ProjectUpdate, ProjectResponse


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_project(self, current_user: User, data: ProjectCreate) -> ProjectResponse:
        organization = (
            self.db.query(Organization)
            .filter(Organization.id == data.organization_id, Organization.owner_id == current_user.id)
            .first()
        )
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
        project = self.db.query(Project).join(Organization).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("Project not found")
        if project.organization.owner_id != current_user.id:
            raise PermissionError("Not authorized to update this project")

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
        project = self.db.query(Project).join(Organization).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("Project not found")
        if project.organization.owner_id != current_user.id:
            raise PermissionError("Not authorized to delete this project")

        self.db.delete(project)
        self.db.commit()

    def get_dashboard(self, current_user: User, project_id: int) -> dict[str, object]:
        project = self.db.query(Project).join(Organization).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("Project not found")
        if project.organization.owner_id != current_user.id:
            raise PermissionError("Not authorized to view this dashboard")

        documents = self.db.query(Document).filter(Document.project_id == project.id).all()
        total_chunks = (
            self.db.query(DocumentChunk)
            .join(Document)
            .filter(Document.project_id == project.id)
            .count()
        )
        return {
            "project_id": project.id,
            "project_name": project.name,
            "status": "ready",
            "summary": "Project dashboard is ready for frontend integration",
            "document_count": len(documents),
            "chunk_count": total_chunks,
            "updated_at": project.created_at.isoformat() if project.created_at else None,
        }
