
import asyncio
import time
from collections import defaultdict, deque
from threading import Lock

from starlette.types import ASGIApp, Receive, Scope, Send


MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_CODE_REQUEST_BYTES = 16 * 1024
MAX_AGENT_REQUEST_BYTES = 64 * 1024

RATE_WINDOW_SECONDS = 60

RATE_LIMITS = {
    "/api/execution/run-code": 5,
    "/api/execution/run": 20,
    "/api/agent/plan": 20,
}

DEFAULT_API_RATE_LIMIT = 120

_requests = defaultdict(deque)
_rate_lock = Lock()


class ProofRunSecurityMiddleware:
    """Bound request sizes and apply per-client rate limits."""

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _client_ip(scope: Scope) -> str:
        client = scope.get("client")
        if not client:
            return "unknown"
        return str(client[0])

    @staticmethod
    def _limit_for_path(path: str) -> int:
        return RATE_LIMITS.get(path, DEFAULT_API_RATE_LIMIT)

    @staticmethod
    def _body_limit_for_path(path: str) -> int:
        if path == "/api/execution/run-code":
            return MAX_CODE_REQUEST_BYTES

        if path == "/api/agent/plan":
            return MAX_AGENT_REQUEST_BYTES

        return MAX_REQUEST_BODY_BYTES

    @staticmethod
    def _rate_limited(key: tuple, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - RATE_WINDOW_SECONDS

        with _rate_lock:
            timestamps = _requests[key]

            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= limit:
                return True

            timestamps.append(now)
            return False

    @staticmethod
    async def _reject(
        send: Send,
        status_code: int,
        detail: str,
        headers: list | None = None,
    ):
        import json

        body = json.dumps({"detail": detail}).encode("utf-8")

        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]

        if headers:
            response_headers.extend(headers)

        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": response_headers,
        })

        await send({
            "type": "http.response.body",
            "body": body,
        })

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path in ("/", "/health"):
            await self.app(scope, receive, send)
            return

        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        client_ip = self._client_ip(scope)

        limit = self._limit_for_path(path)

        if self._rate_limited((client_ip, path), limit):
            await self._reject(
                send,
                429,
                "Rate limit exceeded. Try again later.",
                [(b"retry-after", b"60")],
            )
            return

        if method in ("POST", "PUT", "PATCH"):
            body_limit = self._body_limit_for_path(path)

            content_lengths = [
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ]

            if len(content_lengths) > 1:
                await self._reject(
                    send, 400, "Invalid Content-Length header."
                )
                return

            if content_lengths:
                try:
                    declared = int(content_lengths[0])
                    if declared < 0:
                        raise ValueError
                except (ValueError, TypeError):
                    await self._reject(
                        send, 400, "Invalid Content-Length header."
                    )
                    return

                if declared > body_limit:
                    await self._reject(
                        send, 413, "Request body exceeds size limit."
                    )
                    return

            body = bytearray()

            while True:
                message = await receive()

                if message["type"] == "http.disconnect":
                    return

                if message["type"] != "http.request":
                    continue

                body.extend(message.get("body", b""))

                if len(body) > body_limit:
                    await self._reject(
                        send, 413, "Request body exceeds size limit."
                    )
                    return

                if not message.get("more_body", False):
                    break

            replayed = False

            async def receive_with_body():
                nonlocal replayed

                if not replayed:
                    replayed = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }

                return await receive()

            await self.app(scope, receive_with_body, send)
            return

        await self.app(scope, receive, send)
