import os
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.schemas import (
    ExecutionRequest,
    ExecutionResult,
    CodeRunRequest,
)
from app.sandbox.code_runner import CodeRunner
from app.core.auth import require_api_key
from app.core.evidence import verify_evidence, create_evidence
from app.core.execution_service import (
    ExecutionServiceError,
    run_verified_smoke_test,
    run_verified_containment_test,
)
from app.sandbox.docker_runner import DockerRunner
from app.storage.execution_store import (
    ExecutionStoreError,
    get_execution,
    list_executions,
)

def is_direct_code_execution_enabled() -> bool:
    return (
        os.getenv(
            "PROOFRUN_ENABLE_DIRECT_CODE_EXECUTION",
            "false",
        ).strip().lower() == "true"
    )

router = APIRouter(
    prefix="/api/execution",
    tags=["execution"],
    dependencies=[Depends(require_api_key)],
)



@router.post("/run-code")
def run_code(request: CodeRunRequest):
    # Fail closed before creating or executing a sandbox.
    if not is_direct_code_execution_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                "Direct code execution is disabled. "
                "Use the approved agent workflow."
            ),
        )

    try:
        result = CodeRunner().run_python(request.code)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Code execution service is unavailable.",
        ) from None

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get(
                "error",
                "Sandbox execution failed.",
            ),
        }

    return {
        "success": True,
        "output": result.get("output", ""),
        "exit_code": result.get("exit_code"),
        "output_truncated": result.get(
            "output_truncated",
            False,
        ),
    }


@router.post("/run", response_model=ExecutionResult)
def run_execution(request: ExecutionRequest):
    services = {
        "smoke_test": run_verified_smoke_test,
        "containment_test": run_verified_containment_test,
    }

    service = services.get(request.command)

    if service is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported execution command",
        )

    try:
        return service(
            runner_factory=DockerRunner,
            evidence_creator=create_evidence,
            evidence_verifier=verify_evidence,
        )
    except ExecutionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc


@router.get("/{execution_id}")
def get_execution_history(execution_id: str):
    try:
        record = get_execution(execution_id)
    except ExecutionStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Execution history is unavailable",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Execution record not found",
        )

    evidence = record.get("evidence")
    output = record.get("output")

    if not isinstance(evidence, dict):
        raise HTTPException(
            status_code=500,
            detail="Stored execution evidence is invalid",
        )

    if (
        evidence.get("execution_id") != record.get("execution_id")
        or evidence.get("timestamp") != record.get("timestamp")
        or evidence.get("output_sha256") != record.get("output_sha256")
    ):
        raise HTTPException(
            status_code=500,
            detail="Stored execution evidence is inconsistent",
        )

    if not isinstance(output, str):
        raise HTTPException(
            status_code=409,
            detail="Original output unavailable for verification",
        )

    if not verify_evidence(output, evidence):
        raise HTTPException(
            status_code=500,
            detail="Stored execution evidence verification failed",
        )

    if record.get("exit_code") != evidence.get("exit_code"):
        raise HTTPException(
            status_code=500,
            detail="Stored execution exit code is inconsistent",
        )

    return {
        **record,
        "verification_status": "verified",
    }


@router.get("/")
def list_execution_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        records = list_executions(
            limit=limit,
            offset=offset,
        )
    except ExecutionStoreError as exc:
        raise HTTPException(
            status_code=503,
            detail="Execution history is unavailable",
        ) from exc

    for record in records:
        evidence = record.get("evidence")
        output = record.get("output")

        if output is None:
            record["verification_status"] = "legacy_unverifiable"
            continue

        if (
            not isinstance(output, str)
            or not isinstance(evidence, dict)
            or evidence.get("execution_id") != record.get("execution_id")
            or evidence.get("timestamp") != record.get("timestamp")
            or evidence.get("output_sha256") != record.get("output_sha256")
            or evidence.get("exit_code") != record.get("exit_code")
            or not verify_evidence(output, evidence)
        ):
            raise HTTPException(
                status_code=500,
                detail="Stored execution evidence verification failed",
            )

        record["verification_status"] = "verified"

    return {
        "items": records,
        "limit": limit,
        "offset": offset,
        "count": len(records),
    }
