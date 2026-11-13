from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, document_processing, embeddings, knowledge_base, projects, retrieval, uploads, chat, analytics,dashboard,test_cases,test_execution,knowledge,workflows
from app.core.exceptions import register_exception_handlers
from app.core.config import settings
from app.core.request_context import (
    RequestContextMiddleware,
    configure_structured_logging,
)
from app.database.connection import Base, engine
from app.models import document, document_chunk, document_embedding, organization, project, user,project_activity,chat_history,chat_session,test_case,test_case_evidence,test_case_generation_run,project_requirement,test_case_requirement,workflow_run,workflow_task,workflow_task_attempt


configure_structured_logging()

if settings.AUTO_CREATE_SCHEMA:
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="TestNova AI",description="AI Quality Engineering Platform",version="1.0.0")

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(knowledge_base.router)
app.include_router(document_processing.router)
app.include_router(embeddings.router)
app.include_router(retrieval.router)
app.include_router(analytics.router)
app.include_router(dashboard.router)
app.include_router(test_cases.router)
app.include_router(test_execution.router)
app.include_router(knowledge.router)
app.include_router(workflows.router)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(RequestContextMiddleware)


@app.get("/")
def home():
    return {"success": True, "message": "Service is healthy", "data": {"message": "TestNova AI Backend Running 🚀"}, "errors": None}