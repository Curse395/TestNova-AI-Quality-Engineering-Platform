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

        logger.info(f"LLM initialized successfully with model: {self.model_name}")

        self.generation_config=types.GenerateContentConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            max_output_tokens=self.max_output_tokens,
        )

    def _validate_configuration(self):
        if not self.api_key:
            raise ValueError("Gemini API Key not found")

    def _initialize_client(self):
        return genai.Client(api_key=self.api_key)

    def generate_content(self,system_prompt:str,user_prompt:str,)-> dict:
        full_prompt=f"""{system_prompt} User: {user_prompt}"""

        try:
            print(f"Using model: {self.model_name}")
            response=self.client.models.generate_content(model=self.model_name,contents=full_prompt,config=self.generation_config,)

            return{
                "success": True,
                "answer":response.text,
                "model":self.model_name,
            }

        except Exception as e:
            logger.exception("Gemini generation failed")

            return{
                "success":False,
                "answer":"",
                "model":self.model_name,
                "error":str(e),
            }