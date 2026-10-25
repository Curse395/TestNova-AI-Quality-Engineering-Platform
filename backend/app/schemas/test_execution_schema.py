from typing import Any, Literal
from pydantic import BaseModel,Field,HttpUrl,ConfigDict

class APIRequestConfig(BaseModel):

    model_config=ConfigDict(extra="forbid")
    method:Literal["GET","POST","PUT","PATCH","DELETE"]
    url:HttpUrl
    headers:dict[str,str]=Field(default_factory=dict)
    params:dict[str,str|int|float|bool]=Field(default_factory=dict)
    json_body:dict[str,Any]|list[Any]|None=None
    expected_status_code:int=Field(ge=100,le=599)
    expected_json_fields:dict[str,Any]=Field(default_factory=dict)
    timeout_seconds:float=Field(default=10.0,gt=0,le=30)

class APIExecutionRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    request:APIRequestConfig