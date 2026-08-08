from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    DATABASE_URL:str
    GEMINI_API_KEY:str
    GEMINI_MODEL:str = "gemini-3.5-flash-lite"

    TEMPERATURE:float=0.2
    MAX_OUTPUT_TOKENS:int=4096
    TOP_P:float=0.95
    TOP_K:int=40

    model_config={"env_file":".env","extra":"ignore"}

settings=Settings()