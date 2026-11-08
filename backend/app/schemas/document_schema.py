from datetime import datetime

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    project_id: int
    uploaded_at: datetime | None = None
    uploaded_by_user_id: int | None = None
    processing_status: str = "uploaded"
    processing_error: str | None = None
    source_type: str = "document"

    model_config = {"from_attributes": True}
