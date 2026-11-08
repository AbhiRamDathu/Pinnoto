import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="ProofRunAPIKey",
    auto_error=False,
)


def require_api_key(
    api_key: str | None = Depends(api_key_header),
) -> bool:
    expected = os.getenv("PROOFRUN_API_KEY", "").strip()

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured.",
        )

    if not api_key or not hmac.compare_digest(
        api_key.strip(), expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    return True
