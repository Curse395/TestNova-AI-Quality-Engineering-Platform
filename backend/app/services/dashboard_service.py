from sqlalchemy.orm import Session
from sqlalchemy import func
import math
from app.models.organization import Organization
from app.models.project import Project
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.project_activity import ProjecActivity
from app.services.recomendation_service import RecommendationService


class DashboardService:

    def __init__(self,db:Session):
        self.db=db
        self.recommendation_service=RecommendationService(db)

    def get_dashboard(self, current_user_id:int):
        organizations=(self.db.query(Organization).filter(Organization.owner_id==current_user_id).all())

        active_projects=[]

        total_projects=0
        total_documents=0
        total_processed_documents=0
        total_chunks=0
        total_embeddings=0

        healthy=0
        needs_review=0
        critical=0

        for organization in organizations:
            projects=(self.db.query(Project).filter(Project.organitzation_id==organization.id).all())

            for project in projects:
                total_projects += 1

                uploaded_documents=(self.db.query(func.count(Document.id))
                                    .filter(Document.project_id==project.id).scalar())
                processed_documents=(self.db.query(func.count(func.distinct(DocumentChunk.document_id)))
                                     .join(Document, Document.id==DocumentChunk.document_id)
                                     .filter(Document.project_id==project.id).scalar())
                document_count=uploaded_documents
                chunk_count=(self.db.query(func.count(DocumentChunk.id))
                             .join(Document, Document.id==DocumentChunk.document_id)
                             .filter(Document.project_id==project.id).scalar())
                embedding_count=(self.db.query(func.count(DocumentEmbedding.id))
                                 .join(DocumentChunk,DocumentChunk.id==DocumentEmbedding.chunk_id)
                                 .join(Document,Document.id==DocumentChunk.document_id)
                                 .filter(Document.project_id==project.id).scalar())

                processing_coverage=(round((processed_documents/uploaded_documents)*100, 2)
                                     if uploaded_documents>0
                                     else 0)

                chunk_embedding_coverage=(round((embedding_count / chunk_count) * 100, 2)
                                          if chunk_count>0
                                          else 0)

                embedding_coverage = round((processing_coverage*0.5)+(chunk_embedding_coverage * 0.5),2)

                project_health=embedding_coverage

                if project_health==100:
                    status="Healthy"
                elif project_health>= 70:
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
                    "embedding_coverage":embedding_coverage,
                    "status":status
                })

                total_documents += document_count
                total_processed_documents += processed_documents
                total_chunks += chunk_count
                total_embeddings += embedding_count

        overall_coverage=(round((total_embeddings/total_chunks)*100,2)
                          if total_chunks>0
                          else 0)

        processing_coverage_total=(round((total_processed_documents/total_documents)*100,2)
                                   if total_documents>0
                                   else 0)

        knowledge_health = round((processing_coverage_total*0.5)+(overall_coverage*0.5), 2)

        healthy_percentage = (round((healthy/total_projects)*100, 2)
                              if total_projects>0
                              else 0)

        release_confidence_raw = (
            (knowledge_health * 0.40) +
            (healthy_percentage * 0.30) +
            (overall_coverage * 0.30)
        )
        release_confidence = math.floor(release_confidence_raw + 0.5)

        if release_confidence >= 90:
            recomendation=("Knowledge base is complete and ready for retrieval.")
        elif release_confidence >= 70:
            recomendation=("Improve document processing and embedding coverage.")
        else:
            recomendation=("Knowledge coverage is incomplete. Additional processing is recommended.")

        high_risk_projects=critical
        medium_risk_projects=needs_review
        healthy_projects=healthy

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

        performance_trend=(self.db.query(ProjecActivity).filter(ProjecActivity.project_id.in_([p["id"] for p in active_projects])).order_by(ProjecActivity.created_at.asc()).all())

        trend_data=[{
            "date":activity.created_at.isoformat(),
            "documents":activity.documents,
            "chunks":activity.chunks,
            "embedding":activity.embeddings
        }
        for activity in performance_trend]

        knowledge_distribution=[{
            "name":"Documents",
            "value":total_documents
        },
        {
            "name":"Chunks",
            "value":total_chunks
        },
        {
            "name":"Embedding",
            "value":total_embeddings
        }]

        dashboard={
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
                        "coverage_uplift":None,
                        "flake_reduction":None,
                        "time_saved_minutes":None,
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
                        "knowledge_distribution":knowledge_distribution
                    },
                    "assistant":{
                        "suggestions":assistant_suggestion
                    },
                    "performance_trend":trend_data
                }
        dashboard["assistant"]={"suggestions":self.recommendation_service.get_workspace_recomendations(dashboard)}

        return dashboard

    def get_dashboard_insights(self,current_user_id:int):

        dashboard=self.get_dashboard(current_user_id)
        release_confidence=dashboard["quality_center"]["release_confidence"]
        knowledge_health=dashboard["quality_center"]["knowledge_health"]
        overall_coverage=dashboard["overview"]["overall_coverage"]

        if release_confidence>=90:
            summary=(
                f"Your knowledge base has {knowledge_health}% processing health "
                f"and {overall_coverage}% embedding coverage."
            )
        elif release_confidence >= 70:
            summary=(
                f"Your knowledge base is mostly complete, but improvements are recommended. "
                f"Current processing health is {knowledge_health}%."
            )
        else:
            summary=(
                f"Knowledge readiness is low because parts of the knowledge base are incomplete. "
                f"Processing health is {knowledge_health}% and embedding coverage is {overall_coverage}%."
            )

        issues=[]

        if dashboard["overview"]["overall_coverage"] < 100:
            missing_embeddings=(
                dashboard["overview"]["total_chunks"]- dashboard["overview"]["total_embeddings"]
            )
            issues.append({
                "title":"missing embeddings",
                "description":f"{missing_embeddings} chunks do not have embeddings ",
                "severity":"High"
            })

        if dashboard["live_health"]["needs_review"] >0:
            issues.append({
                "title":"Projects need review",
                "description":f'{dashboard["live_health"]["needs_review"]} project(s) require attention.',
                "severity":"Medium"
            })

        if dashboard["live_health"]["critical"] >0:
            issues.append({
                "title":"Critical Projects",
                "description":f'{dashboard["live_health"]["critical"]} critical project(s) detected',
                "severity":"High"
            })

        recommendations=[]

        if dashboard["overview"]["overall_coverage"] < 100:
            recommendations.append("Generate embedding for all processed document chunks.")

        if dashboard["live_health"]["needs_review"]>0:
            recommendations.append("Review projects marked as 'Needs Review'.")

        if dashboard["live_health"]["critical"]>0:
            recommendations.append("Resolve projects with critical knowledge coverage.")

        if dashboard["quality_center"]["release_confidence"]>=90:
            recommendations.append("Workspace knowledge coverage is complete.")

        estimated_confidence=release_confidence

        if dashboard["overview"]["overall_coverage"]< 100:
            estimated_confidence += 30

        if dashboard["live_health"]["needs_review"]>0:
            estimated_confidence += 15

        if dashboard["live_health"]["critical"]>0:
            estimated_confidence += 10

        estimated_confidence = min(100,estimated_confidence)

            
        return{
            "release_confidence":dashboard["quality_center"]["release_confidence"],
            "summary":summary,
            "issues":issues,
            "recommendations":recommendations,
            "estimated_confidence_after_fix":estimated_confidence
        }