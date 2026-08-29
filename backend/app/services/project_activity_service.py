from sqlalchemy.orm import Session
from app.models.project_activity import ProjecActivity

class ProjectActivityService:
    def __init__(self,db:Session):
        self.db=db

    def record_activity(self,
                        project_id:int,
                        documents:int,
                        chunks:int,
                        embeddings:int):
        latest=(self.db.query(ProjecActivity).filter(ProjecActivity.project_id==project_id).order_by(ProjecActivity.created_at.desc()).first())

        if latest:
            if (latest.documents==documents
                and latest.chunks==chunks
                and latest.embeddings==embeddings):
                return latest
            
        activity=ProjecActivity(project_id=project_id,
                                documents=documents,
                                chunks=chunks,
                                embeddings=embeddings)
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)

        return activity