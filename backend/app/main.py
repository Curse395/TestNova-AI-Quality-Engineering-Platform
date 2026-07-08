from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.connection import Base,engine
from app.models import user
from app.api import auth

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="TestNova AI",
    description="AI Quality Engineering Platform",
    version="1.0.0"
)

app.include_router(auth.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "TestNova AI Backend Running 🚀"
    }