import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security_middleware import _requests, _rate_lock


def reset_rate_limits():
    with _rate_lock:
        _requests.clear()


def test_code_execution_request_size_limit():
    with TestClient(app) as client:
        response = client.post(
            "/api/execution/run-code",
            content=b"x" * (16 * 1024 + 1),
        )

    assert response.status_code == 413


def test_code_execution_rate_limit(monkeypatch):
    reset_rate_limits()

    monkeypatch.setenv(
        "PROOFRUN_API_KEY",
        "correct-test-secret",
    )

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/execution/run-code",
                headers={"X-API-Key": "wrong-secret"},
                json={"code": "print('test')"},
            )
            for _ in range(6)
        ]

    assert all(
        response.status_code == 401
        for response in responses[:5]
    )

    assert responses[5].status_code == 429


def test_health_is_not_rate_limited():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

@pytest.fixture(autouse=True)
def reset_security_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()