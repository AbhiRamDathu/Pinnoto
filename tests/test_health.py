
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ProofRun",
    }


def test_docker_health_endpoint():
    response = client.get("/api/health/docker")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["engine_version"]
