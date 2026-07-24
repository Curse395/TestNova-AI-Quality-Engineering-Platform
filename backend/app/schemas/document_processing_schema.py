from pydantic import BaseModel


class DocumentProcessingResponse(BaseModel):
    document_id: int
    chunks_created: int
    status: str

    model_config = {"from_attributes": True}
