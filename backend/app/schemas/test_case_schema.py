from pydantic import BaseModel,Field
from typing import Literal

__test__=False
TestCategory=Literal["positive","negative","boundary","edge"]
TestPriority=Literal["low","high","medium","critical"]
DocumentSourceType=Literal["document","requirements","bug_report","test_log","technical_document","api_catalogue"]

class TestCaseGenerationRequest(BaseModel):
    requirements_prompt:str=Field(min_length=5,max_length=10000)
    document_ids:list[int]|None=None
    source_types:list[DocumentSourceType]|None=None
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
