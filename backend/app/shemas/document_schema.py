from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    storage_path: str
    project_id: int

    model_config = {"from_attributes": True}


class DocumentUploadRequest(BaseModel):
    project_id: int
