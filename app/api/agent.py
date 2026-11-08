import time
import hashlib
import json
import secrets
from time import time as wall_time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.core.auth import require_api_key
from app.core.inference import InferenceError, generate_response
from app.core.agent_schemas import (
    AgentPlan,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentApprovalRequest,
    AgentExecutionResponse,
)
from app.core.evidence import create_evidence, verify_evidence
from app.core.execution_service import (
    ExecutionServiceError,
    run_verified_smoke_test,
)
from app.sandbox.docker_runner import DockerRunner
from app.storage.approval_store import (
    ApprovalStoreError,
    save_approval,
    consume_approval,
)

router = APIRouter(
    prefix="/api/agent",
    tags=["agent"],
    dependencies=[Depends(require_api_key)],
)

APPROVAL_TTL_SECONDS = 300

def _now_epoch_seconds() -> float:
    """Return Unix epoch time for persistent approval expiry."""
    return time.time()

def _plan_hash(plan: AgentPlan) -> str:
    canonical = json.dumps(
        plan.model_dump(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def _generate_plan(task: str) -> AgentPlan:
    prompt = (
        "Return only a JSON object with exactly these fields: "
        '"summary" (string) and "actions" (array). '
        'The actions array must contain exactly one item: "smoke_test". '
        "Do not execute anything or claim execution occurred.\n"
        f"Task: {task}"
    )

    try:
        raw_response = generate_response(prompt)
    except InferenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="The planning service is unavailable.",
        ) from exc

    try:
        data = json.loads(raw_response)
        plan = AgentPlan.model_validate(data)

        if plan.actions != ["smoke_test"]:
            raise ValueError("Unexpected action list.")

        return plan

    except (json.JSONDecodeError, ValidationError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Inference returned an invalid plan.",
        ) from None


@router.post("/plan", response_model=AgentPlanResponse)
def create_plan(request: AgentPlanRequest):
    plan = _generate_plan(request.task)

    digest = _plan_hash(plan)
    approval_id = secrets.token_urlsafe(32)

    now = wall_time()
    expires_at = now + APPROVAL_TTL_SECONDS

    created_at = datetime.fromtimestamp(
        now,
        tz=timezone.utc,
    ).isoformat()

    try:
        save_approval(
            approval_id=approval_id,
            plan=plan.model_dump(),
            plan_hash=digest,
            expires_at=expires_at,
            created_at=created_at,
        )
    except ApprovalStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Approval storage is unavailable.",
        ) from exc

    return {
        "approval_id": approval_id,
        "plan_hash": digest,
        "proposed_plan": plan.model_dump(),
        "approval_expires_in_seconds": APPROVAL_TTL_SECONDS,
        "execution_started": False,
    }


@router.post(
    "/execute",
    response_model=AgentExecutionResponse,
)
def execute_plan(request: AgentApprovalRequest):

    # Atomically consume the approval from SQLite.
    try:
        entry = consume_approval(
            approval_id=request.approval_id,
            plan_hash=request.plan_hash,
            now=_now_epoch_seconds(),
        )
    except ApprovalStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Approval storage is unavailable.",
        ) from exc

    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="Approval is invalid, expired, or already used.",
        )

    # Validate the persisted plan.
    try:
        plan = AgentPlan.model_validate(entry["plan"])
    except (ValidationError, KeyError, TypeError):
        raise HTTPException(
            status_code=500,
            detail="Stored plan validation failed.",
        ) from None

    # Verify that the stored plan still matches its original digest.
    calculated_hash = _plan_hash(plan)

    if not secrets.compare_digest(
        calculated_hash,
        entry["plan_hash"],
    ):
        raise HTTPException(
            status_code=500,
            detail="Stored plan integrity verification failed.",
        )

    # Defense in depth: enforce the exact allowlisted action.
    if plan.actions != ["smoke_test"]:
        raise HTTPException(
            status_code=400,
            detail="Plan contains a disallowed action.",
        )

    # Execute only after successful approval consumption and validation.
    try:
        result = run_verified_smoke_test(
            runner_factory=DockerRunner,
            evidence_creator=create_evidence,
            evidence_verifier=verify_evidence,
        )
    except ExecutionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc

    return {
        "plan": plan.model_dump(),
        "plan_hash": entry["plan_hash"],
        "execution_started": True,
        "results": [result],
    }
