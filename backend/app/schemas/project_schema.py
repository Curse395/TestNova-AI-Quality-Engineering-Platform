from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    organization_id: int


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    organization_id: int

    model_config = {"from_attributes": True}