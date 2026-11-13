import math

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    DATABASE_URL:str
    GEMINI_API_KEY:str
    JWT_SECRET_KEY: str = Field(min_length=32)
    LLM_PROVIDER: str = "gemini"
    GEMINI_MODEL:str = "gemini-3.5-flash-lite"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    LLM_FALLBACK_ENABLED: bool = False
    LLM_FALLBACK_PROVIDER: str | None = None
    LLM_FALLBACK_MODEL: str | None = None
    LLM_PRICING: dict[str, dict[str, dict[str, float]]] = Field(
        default_factory=dict
    )
    LLM_PRICING_CURRENCY: str | None = None
    LLM_PRICING_VERSION: str | None = None
    LLM_TELEMETRY_PATH: str | None = None
    LLM_TELEMETRY_MAX_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)
    LLM_TELEMETRY_BACKUP_COUNT: int = Field(default=5, ge=1, le=20)

    TEMPERATURE:float=0.2
    MAX_OUTPUT_TOKENS:int=4096
    TOP_P:float=0.95
    TOP_K:int=40
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)
    LLM_TIMEOUT_SECONDS: float = Field(default=60, gt=0, le=300)
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    AUTO_CREATE_SCHEMA: bool = False
    CHUNK_SIZE_WORDS: int = Field(default=120, ge=1)
    CHUNK_OVERLAP_WORDS: int = Field(default=30, ge=0)
    RETRIEVAL_TOP_K: int = Field(default=4, ge=1)
    RETRIEVAL_MAX_TOP_K: int = Field(default=20, ge=1)
    RETRIEVAL_MIN_SIMILARITY: float = Field(default=0.0, ge=-1.0, le=1.0)
    CONTEXT_TOKEN_BUDGET: int = Field(default=1000, ge=1)
    WORKFLOW_MAX_CONCURRENT_TASKS: int = Field(default=3, ge=1, le=8)
    WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS: int = Field(default=300, gt=0, le=1800)

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret_key(cls, value: str) -> str:
        if len(set(value)) < 8 or value != value.strip():
            raise ValueError(
                "JWT_SECRET_KEY must not be blank or a low-entropy repeated value"
            )
        return value

    @field_validator("LLM_PRICING", mode="before")
    @classmethod
    def validate_llm_pricing(cls, value):
        if not isinstance(value, dict):
            raise ValueError("LLM_PRICING must be a provider/model mapping")
        allowed_rates = {
            "input_per_million_tokens",
            "output_per_million_tokens",
        }
        validated = {}
        for provider, models in value.items():
            if provider not in {"gemini", "groq"} or not isinstance(models, dict):
                raise ValueError("LLM_PRICING contains an invalid provider mapping")
            validated[provider] = {}
            for model, rates in models.items():
                if not isinstance(model, str) or not model.strip():
                    raise ValueError("LLM_PRICING model names cannot be blank")
                if not isinstance(rates, dict) or set(rates) != allowed_rates:
                    raise ValueError(
                        "Each LLM_PRICING model requires input and output "
                        "per-million-token rates"
                    )
                validated[provider][model] = {}
                for rate_name, rate in rates.items():
                    if (
                        isinstance(rate, bool)
                        or not isinstance(rate, (int, float))
                        or not math.isfinite(rate)
                        or rate < 0
                    ):
                        raise ValueError(
                            "LLM_PRICING rates must be finite non-negative numbers"
                        )
                    validated[provider][model][rate_name] = float(rate)
        return validated

    @field_validator("LLM_PRICING_CURRENCY")
    @classmethod
    def validate_llm_pricing_currency(cls, value):
        if value is None:
            return None
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise ValueError("LLM_PRICING_CURRENCY must be a three-letter code")
        return currency

    @field_validator("LLM_PRICING_VERSION", "LLM_TELEMETRY_PATH")
    @classmethod
    def validate_optional_llm_paths_and_versions(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("LLM pricing version and telemetry path cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_llm_configuration(self):
        supported_providers = {"gemini", "groq"}
        self.LLM_PROVIDER = self.LLM_PROVIDER.strip().lower()
        if self.LLM_PROVIDER not in supported_providers:
            raise ValueError("LLM_PROVIDER must be 'gemini' or 'groq'")
        if not self.GEMINI_MODEL.strip() or not self.GROQ_MODEL.strip():
            raise ValueError("Configured LLM model names cannot be blank")
        if self.LLM_PRICING and self.LLM_PRICING_CURRENCY is None:
            raise ValueError(
                "LLM_PRICING_CURRENCY is required when LLM_PRICING is configured"
            )
        if self.LLM_FALLBACK_PROVIDER is not None:
            self.LLM_FALLBACK_PROVIDER = self.LLM_FALLBACK_PROVIDER.strip().lower()
            if self.LLM_FALLBACK_PROVIDER not in supported_providers:
                raise ValueError(
                    "LLM_FALLBACK_PROVIDER must be 'gemini' or 'groq'"
                )
        if self.LLM_FALLBACK_MODEL is not None and not self.LLM_FALLBACK_MODEL.strip():
            raise ValueError("LLM_FALLBACK_MODEL cannot be blank")
        if self.LLM_FALLBACK_ENABLED:
            if self.LLM_FALLBACK_PROVIDER is None:
                raise ValueError(
                    "LLM_FALLBACK_PROVIDER is required when fallback is enabled"
                )
            if self.LLM_FALLBACK_PROVIDER == self.LLM_PROVIDER:
                raise ValueError("Fallback provider must differ from primary provider")
        return self

    model_config={"env_file":".env","extra":"ignore"}

settings=Settings()