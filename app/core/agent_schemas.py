
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AgentPlanRequest(BaseModel):
    model_config = {"extra": "forbid"}

    task: str = Field(min_length=1, max_length=2000)

    @field_validator("task")
    @classmethod
    def task_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Task must not be blank.")
        return value


class AgentPlan(BaseModel):
    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=1, max_length=500)
    actions: list[Literal["smoke_test"]] = Field(
        min_length=1,
        max_length=1,
    )


class AgentPlanResponse(BaseModel):
    proposed_plan: AgentPlan
    execution_started: bool = False
    approval_id: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_expires_in_seconds: int


class AgentApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    approval_id: str = Field(min_length=1, max_length=100)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentExecutionResponse(BaseModel):
    plan: AgentPlan
    plan_hash: str
    execution_started: bool
    results: list[dict]
