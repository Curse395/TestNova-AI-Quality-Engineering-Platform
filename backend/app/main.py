import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, document_processing, embeddings, knowledge_base, projects, retrieval, uploads, chat, analytics,dashboard,test_cases,test_execution,knowledge
from app.core.exceptions import register_exception_handlers
from app.core.responses import ApiResponse, success_response
from app.database.connection import Base, engine
from app.database.schema import ensure_test_case_generation_schema
from app.models import document, document_chunk, document_embedding, organization, project, user,project_activity,chat_history,chat_session,test_case,test_case_evidence,test_case_generation_run


logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)
ensure_test_case_generation_schema(engine)

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
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def home():
    return {"success": True, "message": "Service is healthy", "data": {"message": "TestNova AI Backend Running 🚀"}, "errors": None}