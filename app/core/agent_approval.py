
import hashlib
import hmac
import secrets
import threading
import time

from app.core.agent_schemas import AgentPlan


_APPROVAL_TTL_SECONDS = 300
_lock = threading.Lock()
_pending: dict[str, tuple[str, float]] = {}


def _plan_digest(plan: AgentPlan) -> str:
    canonical = plan.model_dump_json().encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def issue_approval(plan: AgentPlan) -> str:
    """Issue a short-lived, single-use approval token for an exact plan."""
    token = secrets.token_urlsafe(32)
    digest = _plan_digest(plan)
    now = time.monotonic()

    with _lock:
        expired = [
            key for key, (_, expiry) in _pending.items()
            if expiry <= now
        ]
        for key in expired:
            del _pending[key]

        _pending[hashlib.sha256(token.encode()).hexdigest()] = (
            digest,
            now + _APPROVAL_TTL_SECONDS,
        )

    return token


def consume_approval(token: str, plan: AgentPlan) -> bool:
    """Consume approval once, only if it matches the exact approved plan."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    digest = _plan_digest(plan)
    now = time.monotonic()

    with _lock:
        record = _pending.pop(token_hash, None)

        if record is None:
            return False

        expected_digest, expiry = record

        return (
            expiry > now
            and hmac.compare_digest(expected_digest, digest)
        )
