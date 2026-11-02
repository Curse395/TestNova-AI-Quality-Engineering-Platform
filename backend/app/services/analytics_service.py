from sqlalchemy.orm import Session
from sqlalchemy import func 
from app.models.project import Project
from app.models.organization import Organization
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding

class AnalyticsService:
    def __init__(self,db:Session):
        self.db=db

    def get_project_overview(self,project_id:int,current_user_id:int):

        project=(self.db.query(Project).join(Organization).filter(Project.id==project_id,Organization.owner_id==current_user_id).first())
        if not project:
            raise ValueError("Project not found")

        total_documents=(self.db.query(func.count(Document.id)).filter(Document.project_id==project_id).scalar())
        total_chunks=(self.db.query(func.count(DocumentChunk.id)).join(Document).filter(Document.project_id==project_id).scalar())
        total_embeddings=(self.db.query(func.count(DocumentEmbedding.id)).join(DocumentChunk).join(Document).filter(Document.project_id==project_id).scalar())

        return{
            "project_id":project_id,
            "documents":total_documents,
            "chunks":total_chunks,
            "embeddings":total_embeddings,
            "embedding_coverage":round((total_embeddings / total_chunks*100),2)
            if total_chunks > 0 else 0,
        }

    def get_document_statistics(self,current_user_id:int,project_id:int):
        project=(self.db.query(Project).join(Organization).filter(Project.id==project_id,Organization.owner_id==current_user_id).first())
        
        if not project:
            raise ValueError("Project not found")

        documents=(self.db.query(Document).filter(Document.project_id==project.id).all())

        statistics=[]

        for document in documents:
            chunk_count=(self.db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.document_id==document.id).scalar())

            embedding_count=(self.db.query(func.count(DocumentEmbedding.id)).join(DocumentChunk,DocumentEmbedding.chunk_id==DocumentChunk.id).filter(DocumentChunk.document_id==document.id).scalar())

            statistics.append({"document_id":document.id,
                               "filename":document.filename,
                               "chunks":chunk_count,
                               "embeddings":embedding_count,})

        return statistics
        