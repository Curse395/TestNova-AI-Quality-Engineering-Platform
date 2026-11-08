from sqlalchemy.orm import Session
from app.services.retrieval_service import RetrievalService
from app.services.context_builder_service import ContextBuilderService
from app.services.llm_services import LLMService 
from app.services.prompt_builder_service import PromptBuilderService
from app.services.chat_history_service import ChatHistoryService
from app.models.chat_history import ChatHistory

class ChatService:

    def __init__(self, db:Session):
        self.db=db
        self.retrieval_service=RetrievalService(db)
        self.context_builder=ContextBuilderService()
        self.llm_service=LLMService()
        self.prompt_builder=PromptBuilderService()
        self.history_service=ChatHistoryService(db)

    def chat(self,current_user_id:int,project_id:int,question:str,session_id:int):

        session=self.history_service.get_session(session_id=session_id,user_id=current_user_id,project_id=project_id)
        if session is None:
            raise ValueError("chat session not found ")

        retrived_chunks=self.retrieval_service.search_project_context(current_user_id=current_user_id,project_id=project_id,query=question,limit=5,)

        recent_history=(self.db.query(ChatHistory).filter(ChatHistory.session_id==session_id,ChatHistory.user_id==current_user_id,ChatHistory.project_id==project_id).order_by(ChatHistory.created_at.desc(),ChatHistory.id.desc()).limit(5).all())

        conversation_history=""
        for chat in reversed(recent_history):
            conversation_history += (
                f"User: {chat.question}\n"
                f"Assistant: {chat.answer}\n\n"
            )

        context_payload=self.context_builder.build_context(retrived_chunks)

        system_prompt,user_prompt=self.prompt_builder.build_prompt(context=context_payload["context"],conversation_history=conversation_history,question=question)

        response=self.llm_service.generate_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if not response.get("success"):
            raise RuntimeError("The assistant could not generate a response.")

        self.history_service.save_chat(
            user_id=current_user_id,
            project_id=project_id,
            session_id=session_id,
            question=question,
            answer=response["answer"]
        )

        return{ 
            **response,
            "sources":[{
                "document_id": chunks["document_id"],
                "document_name": chunks["document_name"],
                "chunk_id":chunks["chunk_id"],
                "score":chunks["score"],
                "source_type": chunks.get("source_type", "document"),
            }
            for chunks in retrived_chunks
            ]
        }
