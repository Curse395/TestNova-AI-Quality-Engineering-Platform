import os
import logging
from google import genai
from google.genai import types 
from dotenv import load_dotenv

load_dotenv()

logger=logging.getLogger(__name__)

class LLMService:

    def __init__(self):

        self.api_key=os.getenv("GEMINI_API_KEY")
        self.model_name=os.getenv(
            "GEMINI_MODEL",
            "gemini-3.5-flash"
        )
        self.temperature=float(os.getenv("TEMPERATURE","0.2"))
        self.max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS","4096"))
        self.top_p=float(os.getenv("TOP_P","0.95"))
        self.top_k=int(os.getenv("TOP_K","40"))

        self._validate_configuration()
        self.client=self._initialize_client()

        logger.info("LLM initialized successfully with model: %s", self.model_name)

        self.generation_config=types.GenerateContentConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            max_output_tokens=self.max_output_tokens,
        )

    def _validate_configuration(self):
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")

    def _initialize_client(self):
        return genai.Client(api_key=self.api_key)

    @staticmethod
    def _finish_reason(response) -> str | None:
        candidates = getattr(response, "candidates", None)
        candidate = candidates[0] if candidates else None
        reason = getattr(candidate, "finish_reason", None)
        if reason is None:
            return None
        return getattr(reason, "name", str(reason))

    def generate_content(
        self,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
    ) -> dict:
        config = self.generation_config.model_copy(
            update={
                "system_instruction": system_prompt,
                "response_mime_type": response_mime_type,
            }
        )

        try:
            logger.info("Calling Gemini model: %s", self.model_name)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=config,
            )
        except Exception as exc:
            logger.error(
                "Gemini provider request failed: model=%s error_type=%s",
                self.model_name,
                type(exc).__name__,
            )
            return {
                "success": False,
                "answer": "",
                "model": self.model_name,
                "stage": "provider_request",
                "error": "Gemini provider request failed",
            }

        finish_reason = self._finish_reason(response)
        try:
            answer = response.text
        except Exception as exc:
            logger.error(
                "Gemini response text extraction failed: model=%s error_type=%s finish_reason=%s",
                self.model_name,
                type(exc).__name__,
                finish_reason,
            )
            return {
                "success": False,
                "answer": "",
                "model": self.model_name,
                "stage": "response_extraction",
                "finish_reason": finish_reason,
                "error": "Gemini response text could not be extracted",
            }

        if not isinstance(answer, str) or not answer.strip():
            logger.warning(
                "Gemini returned no text: model=%s finish_reason=%s",
                self.model_name,
                finish_reason,
            )
            return {
                "success": False,
                "answer": "",
                "model": self.model_name,
                "stage": "empty_response",
                "finish_reason": finish_reason,
                "error": "Gemini returned no text content",
            }

        logger.info(
            "Gemini response received: model=%s characters=%d finish_reason=%s",
            self.model_name,
            len(answer),
            finish_reason,
        )
        return {
            "success": True,
            "answer": answer,
            "model": self.model_name,
            "stage": "complete",
        }