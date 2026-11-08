
from app.core.evidence import create_evidence, verify_evidence
from app.sandbox.docker_runner import DockerRunner


from app.storage.execution_store import (
    ExecutionStoreError,
    initialize_store,
    save_execution,
)


class ExecutionServiceError(Exception):
    """Safe error raised when sandbox execution cannot be completed."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _run_verified_test(
    runner_method: str,
    runner_factory=DockerRunner,
    evidence_creator=create_evidence,
    evidence_verifier=verify_evidence,
) -> dict:
    """Execute an allowlisted test and verify its signed evidence."""

    result = getattr(runner_factory(), runner_method)()

    if not isinstance(result, dict) or not result.get("success"):
        raise ExecutionServiceError("Sandbox execution failed", 503)

    output = result.get("output")
    exit_code = result.get("exit_code")

    if (
        not isinstance(output, str)
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or exit_code != 0
    ):
        raise ExecutionServiceError(
            "Sandbox returned an invalid execution result", 503
        )

    try:
        evidence = evidence_creator(output=output, exit_code=exit_code)
    except Exception as exc:
        raise ExecutionServiceError(
            "Execution evidence could not be created", 500
        ) from exc

    if not evidence_verifier(output, evidence):
        raise ExecutionServiceError(
            "Execution evidence verification failed", 500
        )


    command = {
        "run_smoke_test": "smoke_test",
        "run_containment_test": "containment_test",
    }.get(runner_method)

    if command is None:
        raise ExecutionServiceError(
            "Unsupported execution type", 400
        )

    try:
        initialize_store()
        save_execution(
            execution_id=evidence["execution_id"],
            timestamp=evidence["timestamp"],
            command=command,
            exit_code=exit_code,
            output=output,
            output_sha256=evidence["output_sha256"],
            evidence=evidence,
            verified=True,
        )
    except Exception as exc:
        raise ExecutionServiceError(
            "Execution record could not be saved", 503
        ) from exc


    return {
        "success": True,
        "output": output,
        "evidence": evidence,
    }


def run_verified_smoke_test(
    runner_factory=DockerRunner,
    evidence_creator=create_evidence,
    evidence_verifier=verify_evidence,
) -> dict:
    """Run the predefined smoke test."""
    return _run_verified_test(
        "run_smoke_test",
        runner_factory,
        evidence_creator,
        evidence_verifier,
    )


def run_verified_containment_test(
    runner_factory=DockerRunner,
    evidence_creator=create_evidence,
    evidence_verifier=verify_evidence,
) -> dict:
    """Run the predefined read-only filesystem containment test."""
    return _run_verified_test(
        "run_containment_test",
        runner_factory,
        evidence_creator,
        evidence_verifier,
    )
