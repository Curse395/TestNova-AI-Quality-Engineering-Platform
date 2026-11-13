import logging

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project

logger = logging.getLogger(__name__)


def get_owned_project(
    db: Session,
    project_id: int,
    user_id: int,
    *,
    for_update: bool = False,
) -> Project | None:
    query = (
        db.query(Project)
        .join(Organization, Project.organitzation_id == Organization.id)
        .filter(
            Project.id == project_id,
            Organization.owner_id == user_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    project = query.first()
    if project is None:
        logger.warning(
            "Owner-scoped project lookup denied: project_id=%s user_id=%s",
            project_id,
            user_id,
        )
    return project


def get_owned_document(
    db: Session,
    document_id: int,
    user_id: int,
    *,
    for_update: bool = False,
) -> Document | None:
    query = (
        db.query(Document)
        .join(Project, Document.project_id == Project.id)
        .join(Organization, Project.organitzation_id == Organization.id)
        .filter(
            Document.id == document_id,
            Organization.owner_id == user_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    document = query.first()
    if document is None:
        logger.warning(
            "Owner-scoped document lookup denied: document_id=%s user_id=%s",
            document_id,
            user_id,
        )
    return document
