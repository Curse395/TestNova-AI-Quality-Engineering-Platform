from sqlalchemy.orm import Session
from sqlalchemy import func 
from app.models.organization import Organization
from app.models.project import Project
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding

class DashboardService:

    def __init__(self,db:Session):
        self.db=db

    def get_dashboard(self, current_user_id:int):
        organizations=(self.db.query(Organization).filter(Organization.owner_id==current_user_id).all())

        active_projects=[]

        total_projects=0
        total_documents=0
        total_chunks=0
        total_embeddings=0

        healthy=0
        needs_review=0
        critical=0


        for organization in organizations:
            projects=(self.db.query(Project).filter(Project.organitzation_id==organization.id).all())

            for project in projects:
                total_projects += 1
                document_count=(self.db.query(func.count(Document.id)).filter(Document.project_id==project.id).scalar())
                chunk_count=(self.db.query(func.count(DocumentChunk.id)).join(Document, Document.id==DocumentChunk.document_id).filter(Document.project_id==project.id).scalar())
                embedding_count=(self.db.query(func.count(DocumentEmbedding.id)).join(DocumentChunk,DocumentChunk.id==DocumentEmbedding.chunk_id).join(Document,Document.id==DocumentChunk.document_id).filter(Document.project_id==project.id).scalar())
                coverage=(round((embedding_count/chunk_count)*100, 2)
                          if chunk_count>0
                          else 0)

                if coverage==100:
                    status="Healthy"
                elif coverage>= 70:
                    status="Needs Review"
                else:
                    status="Critical"

                if status == "Healthy":
                    healthy += 1
                elif status == "Needs Review":
                    needs_review += 1
                else:
                    critical += 1
        

                active_projects.append({
                    "id":project.id,
                    "name":project.name,
                    "documents":document_count,
                    "chunks": chunk_count,
                    "embedding_coverage":coverage,
                    "status":status
                })

                total_documents += document_count
                total_chunks += chunk_count
                total_embeddings += embedding_count

                overall_coverage=(round((total_embeddings/total_chunks)*100,2)
                                  if total_chunks>0
                                  else 0)

                if overall_coverage>= 95:
                    release_confidence=96
                elif overall_coverage>=85:
                    release_confidence=90
                elif overall_coverage>=70:
                    release_confidence=80
                else:
                    release_confidence=65

                high_risk_projects=critical
                medium_risk_projects=needs_review
                healthy_projects=healthy

                knowledge_health = overall_coverage

                if high_risk_projects > 0:
                    recomendation=("Resolve critical projects before release.")
                elif medium_risk_projects > 0:
                    recomendation=("Review medium-risk projects before release.")
                else:
                    recomendation=("Knowledge base is healthy and ready")

                coverage_uplift=min(overall_coverage // 8,15)
                flake_reduction=min(healthy * 12,25)
                time_saved=(total_chunks*5)

                assistant_suggestion=[]
                if total_documents == 0:
                    assistant_suggestion.append("Upload your first document to start buildinng your knowledge base")
                if overall_coverage<100:
                    assistant_suggestion.append("Some documents are missing embedding")
                if critical>0:
                    assistant_suggestion.append("Resolve critical projects before the next release")
                if healthy >0:
                    assistant_suggestion.append("Generate AI-Powered text cases for healthy project")
                if len(assistant_suggestion)==0:
                    assistant_suggestion.append("Your workspace  is healthy. Consider generating a regression suite")

        return{
                    "active_projects":active_projects,
                    "quality_center":{
                        "release_confidence":release_confidence,
                        "knowledge_health":knowledge_health,
                        "healthy_projects":healthy_projects,
                        "medium_risk_projects":medium_risk_projects,
                        "high_risk_projects":high_risk_projects,
                        "recomendation":recomendation
                    },
                    "test_generation":{
                        "coverage_uplift":coverage_uplift,
                        "flake_reduction":flake_reduction,
                        "time_saved_minutes":time_saved,
                    },
                    "overview":{
                        "total_projects":total_projects,
                        "total_documents":total_documents,
                        "total_chunks":total_chunks,
                        "total_embeddings":total_embeddings,
                        "overall_coverage":overall_coverage
                    },
                    "live_health":{
                        "healthy":healthy,
                        "needs_review":needs_review,
                        "critical":critical
                    },
                    "performance":{
                        "documents_processed":total_documents,
                        "chunks_created":total_chunks,
                        "coverage":overall_coverage
                    },
                    "risk":{
                        "high":critical,
                        "medium":needs_review,
                        "low":healthy,
                    },
                    "assistant":{
                        "suggestions":assistant_suggestion
                    }
                }
