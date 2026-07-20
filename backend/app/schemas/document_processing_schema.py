from pydantic import BaseModel


class DocumentProcessingResponse(BaseModel):
    document_id: int
    chunk_count: int

    model_config = {"from_attributes": True}
