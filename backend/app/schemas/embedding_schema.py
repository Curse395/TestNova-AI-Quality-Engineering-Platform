from pydantic import BaseModel


class EmbeddingResponse(BaseModel):
    generated: int

    model_config = {"from_attributes": True}
