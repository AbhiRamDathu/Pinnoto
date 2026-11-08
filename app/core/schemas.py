from typing import Literal

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    command: Literal["smoke_test", "containment_test"] = Field(
        description="Run an explicitly allowlisted sandbox test."
    )


class ExecutionResult(BaseModel):
    success: bool
    output: str
    evidence: dict

class CodeRunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(min_length=1, max_length=8000)