
from fastapi.testclient import TestClient


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("PROOFRUN_API_KEY", "correct-test-secret")

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/execution/run-code",
            json={"code": "print('should not execute')"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key."


def test_invalid_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("PROOFRUN_API_KEY", "correct-test-secret")

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/execution/run-code",
            headers={"X-API-Key": "wrong-secret"},
            json={"code": "print('should not execute')"},
        )

    assert response.status_code == 401


def test_missing_server_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("PROOFRUN_API_KEY", raising=False)

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/execution/run-code",
            json={"code": "print('should not execute')"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "API authentication is not configured."
    )


def test_health_remains_public(monkeypatch):
    monkeypatch.delenv("PROOFRUN_API_KEY", raising=False)

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_valid_api_key_allows_request(monkeypatch):
    monkeypatch.setenv("PROOFRUN_API_KEY", "correct-test-secret")

    monkeypatch.setenv(
        "PROOFRUN_ENABLE_DIRECT_CODE_EXECUTION",
        "true",
    )

    from fastapi.testclient import TestClient
    from app.main import app
    from app.sandbox.code_runner import CodeRunner

    monkeypatch.setattr(
        CodeRunner,
        "run_python",
        lambda self, code: {
            "success": True,
            "output": "AUTH_TEST_OK",
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/execution/run-code",
            headers={"X-API-Key": "correct-test-secret"},
            json={"code": "print('hello')"},
        )

    assert response.status_code == 200
    assert response.json()["output"] == "AUTH_TEST_OK"
