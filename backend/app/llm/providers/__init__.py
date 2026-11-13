from functools import lru_cache

from app.core.config import settings
from app.llm.contracts import LLMConfigurationException, LLMProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider


def _configured_model(provider_name: str, model_name: str | None) -> str:
    if model_name is not None:
        selected_model = model_name.strip()
    elif provider_name == "gemini":
        selected_model = settings.GEMINI_MODEL.strip()
    elif provider_name == "groq":
        selected_model = settings.GROQ_MODEL.strip()
    else:
        raise LLMConfigurationException(
            provider_name or "unknown",
            "Unsupported LLM provider configured",
        )
    if not selected_model:
        raise LLMConfigurationException(
            provider_name,
            "LLM model is not configured",
        )
    return selected_model


def create_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
) -> LLMProvider:
    configured_provider = (
        settings.LLM_PROVIDER if provider_name is None else provider_name
    )
    selected_provider = configured_provider.strip().lower()
    if selected_provider not in {"gemini", "groq"}:
        raise LLMConfigurationException(
            selected_provider or "unknown",
            "Unsupported LLM provider configured",
        )
    selected_model = _configured_model(selected_provider, model_name)

    if selected_provider == "gemini":
        return GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model_name=selected_model,
        )
    return GroqProvider(
        api_key=settings.GROQ_API_KEY,
        model_name=selected_model,
    )


@lru_cache(maxsize=8)
def get_provider(provider_name: str, model_name: str | None = None) -> LLMProvider:
    selected_provider = provider_name.strip().lower()
    selected_model = _configured_model(selected_provider, model_name)
    return create_provider(selected_provider, selected_model)


@lru_cache(maxsize=1)
def get_default_provider() -> LLMProvider:
    return get_provider(settings.LLM_PROVIDER, None)


__all__ = ["create_provider", "get_default_provider", "get_provider"]
