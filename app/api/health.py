from fastapi import APIRouter, HTTPException

from app.sandbox.docker_runner import DockerRunner

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/docker")
def docker_health():
    try:
        runner = DockerRunner()
        result = runner.health_check()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Docker execution service is unavailable",
        ) from None

    if not result.get("available"):
        raise HTTPException(
            status_code=503,
            detail="Docker execution service is unavailable",
        )

    return result
