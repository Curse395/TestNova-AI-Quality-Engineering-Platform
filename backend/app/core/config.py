from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    DATABASE_URL:str
    GEMINI_API_KEY:str
    JWT_SECRET_KEY: str = Field(min_length=32)
    GEMINI_MODEL:str = "gemini-3.5-flash-lite"

    TEMPERATURE:float=0.2
    MAX_OUTPUT_TOKENS:int=4096
    TOP_P:float=0.95
    TOP_K:int=40
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    AUTO_CREATE_SCHEMA: bool = False
    CHUNK_SIZE_WORDS: int = Field(default=120, ge=1)
    CHUNK_OVERLAP_WORDS: int = Field(default=30, ge=0)
    RETRIEVAL_TOP_K: int = Field(default=4, ge=1)
    RETRIEVAL_MAX_TOP_K: int = Field(default=20, ge=1)
    RETRIEVAL_MIN_SIMILARITY: float = Field(default=0.0, ge=-1.0, le=1.0)
    CONTEXT_TOKEN_BUDGET: int = Field(default=1000, ge=1)

    model_config={"env_file":".env","extra":"ignore"}

settings=Settings()