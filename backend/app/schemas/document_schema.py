from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    project_id: int
    processing_status: str = "uploaded"
    processing_error: str | None = None
    source_type: str = "document"

    model_config = {"from_attributes": True}
