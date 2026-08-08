from sqlalchemy.orm import Session
from app.services.retrieval_service import RetrievalService
from app.services.context_builder_service import ContextBuilderService
from app.services.llm_services import LLMService 

class ChatService:

    def __init__(self, db:Session):
        self.db=db
        self.retrieval_service=RetrievalService(db)
        self.context_builder=ContextBuilderService()
        self.llm_service=LLMService()

    def chat(self,current_user_id:int,project_id:int,question:str):

        retrived_chunks=self.retrieval_service.search_project_context(current_user_id=current_user_id,
                                                                      project_id=project_id,
                                                                      query=question,
                                                                      limit=5,)

        context_payload=self.context_builder.build_context(retrived_chunks)

        system_prompt=f"""
You are TestNov AI.

you are an AI Quality Engineering Assistant.

Answer ONLY using the provided project documntation.
if the answer is not available in the documentation, clearly say: 
    ' I couldn't find this information in the uploaded project documents.
    
    Project COnext:
    {context_payload["context"]}
"""
        return self.llm_service.generate_content(
            system_prompt=system_prompt,
            user_prompt=question,
        )

