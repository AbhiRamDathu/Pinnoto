
import hashlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    # Isolate this test from the user's real execution database.
    db_path = tmp_path / "api-executions.sqlite3"
    monkeypatch.setenv("PROOFRUN_DB_PATH", str(db_path))

    from app.storage import execution_store

# Patch the already-imported module's cached default database path.
    monkeypatch.setattr(execution_store, "DEFAULT_DB_PATH", db_path)

    from app.main import app
    from app.storage.execution_store import initialize_store, save_execution

    initialize_store(db_path)

    # Use genuine, correctly signed evidence for the test record.
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.core import evidence as evidence_module

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    monkeypatch.setenv(
        "PROOFRUN_ED25519_PRIVATE_KEY",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.setattr(
        evidence_module,
        "TRUSTED_PUBLIC_KEY",
        base64.b64encode(public_bytes).decode("ascii"),
    )
    evidence_module._load_private_key.cache_clear()

    output = "PROOFRUN_SMOKE_OK\n"
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    evidence = evidence_module.create_evidence(output, 0)

    save_execution(
        execution_id=evidence["execution_id"],
        timestamp=evidence["timestamp"],
        command="smoke_test",
        exit_code=0,
        output=output,
        output_sha256=output_hash,
        evidence=evidence,
        verified=True,
        db_path=db_path,
    )

    try:
        with TestClient(app, headers={"X-API-Key": "test-proofrun-key"}) as client:
            yield client
    finally:
        evidence_module._load_private_key.cache_clear()


def test_execution_history_api_returns_verified_records(api_client):
    response = api_client.get("/api/execution/")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["verification_status"] == "verified"
    assert data["items"][0]["output"] == "PROOFRUN_SMOKE_OK\n"



def test_execution_history_api_returns_single_verified_record(api_client):
    listing = api_client.get("/api/execution/")

    assert listing.status_code == 200, (
        f"History listing failed: "
        f"HTTP {listing.status_code}: {listing.text}"
    )

    data = listing.json()
    assert "items" in data, f"Unexpected response body: {data}"
    assert data["count"] == 1

    execution_id = data["items"][0]["execution_id"]
    response = api_client.get(f"/api/execution/{execution_id}")

    assert response.status_code == 200, response.text
    assert response.json()["execution_id"] == execution_id
    assert response.json()["output"] == "PROOFRUN_SMOKE_OK\n"


def test_execution_history_api_returns_404_for_missing_id(api_client):
    response = api_client.get("/api/execution/nonexistent-execution-id")

    assert response.status_code == 404
    assert response.json()["detail"] == "Execution record not found"

def test_execution_service_rejects_boolean_exit_code():
    from unittest.mock import MagicMock

    import pytest

    from app.core.execution_service import (
        ExecutionServiceError,
        _run_verified_test,
    )

    runner = MagicMock()
    runner.run_smoke_test.return_value = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "exit_code": False,
    }

    with pytest.raises(ExecutionServiceError):
        _run_verified_test(
            "run_smoke_test",
            runner_factory=lambda: runner,
        )


def test_execution_service_rejects_nonzero_exit_code():
    from unittest.mock import MagicMock

    import pytest

    from app.core.execution_service import (
        ExecutionServiceError,
        _run_verified_test,
    )

    runner = MagicMock()
    runner.run_smoke_test.return_value = {
        "success": True,
        "output": "PROOFRUN_SMOKE_OK\n",
        "exit_code": 1,
    }

    with pytest.raises(ExecutionServiceError):
        _run_verified_test(
            "run_smoke_test",
            runner_factory=lambda: runner,
        )