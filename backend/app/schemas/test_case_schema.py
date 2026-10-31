from pydantic import BaseModel,Field,ConfigDict
from typing import Literal

__test__=False
TestCategory=Literal["positive","negative","boundary","edge"]
TestPriority=Literal["low","high","medium","critical"]

class TestCaseGenerationRequest(BaseModel):
    requirements_prompt:str=Field(min_length=5,max_length=10000)
    document_ids:list[int]|None=None
    max_cases:int=Field(default=5,ge=1,le=20)
    categories:list[TestCategory]=Field(default_factory=lambda:["positive","negative","boundary","edge"])

class TestCaseStep(BaseModel):
    action:str=Field(min_length=1,max_length=2000)
    expected_result:str=Field(min_length=1,max_length=2000)

class GeneratedTestCase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    category: TestCategory
    priority: TestPriority
    preconditions: str | None = None
    steps: list[TestCaseStep] = Field(min_length=1, max_length=30)
    expected_result: str = Field(min_length=1)
    evidence_chunk_ids: list[int] = Field(min_length=1)

class TestCaseGenerationResponse(BaseModel):
    success: bool
    message: str
    generated_count: int
    test_cases: list[dict]

class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    description: str
    category: TestCategory
    priority: TestPriority
    preconditions: str | None
    steps: list[TestCaseStep]
    expected_result: str
    review_status: str