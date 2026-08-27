from sqlalchemy.orm import Session
from app.services.retrieval_service import RetrievalService
from app.services.context_builder_service import ContextBuilderService
from app.services.llm_services import LLMService 
from app.services.prompt_builder_service import PromptBuilderService

class ChatService:

    def __init__(self, db:Session):
        self.db=db
        self.retrieval_service=RetrievalService(db)
        self.context_builder=ContextBuilderService()
        self.llm_service=LLMService()
        self.prompt_builder=PromptBuilderService()

    def chat(self,current_user_id:int,project_id:int,question:str):

        retrived_chunks=self.retrieval_service.search_project_context(current_user_id=current_user_id,
                                                                      project_id=project_id,
                                                                      query=question,
                                                                      limit=5,)

        context_payload=self.context_builder.build_context(retrived_chunks)

        system_prompt,user_prompt=self.prompt_builder.build_prompt(context=context_payload["context"],question=question)

        response=self.llm_service.generate_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        return{ 
            **response,
            "sources":[{
                "document_id": chunks["document_id"],
                "document_name": chunks["document_name"],
                "chunk_id":chunks["chunk_id"],
                "score":chunks["score"]
            }
            for chunks in retrived_chunks
            ]
        }

