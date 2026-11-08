
from app.core.evidence import create_evidence, verify_evidence

from fastapi.testclient import TestClient

from app.main import app
from app.core.evidence import verify_evidence

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey




def test_evidence_contains_unique_execution_ids():
    first = create_evidence("PROOFRUN_SMOKE_OK\n", 0)
    second = create_evidence("PROOFRUN_SMOKE_OK\n", 0)

    assert first["execution_id"] != second["execution_id"]
    assert first["output_sha256"] == second["output_sha256"]
    assert first["hash_algorithm"] == "sha256"
    assert first["exit_code"] == 0
    assert first["container_image"] == (
        "alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8"
    )
    assert first["timestamp"]


def test_valid_evidence_verifies():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    assert verify_evidence(output, evidence) is True


def test_tampered_output_is_rejected():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    assert verify_evidence("TAMPERED_OUTPUT\n", evidence) is False


def test_unsupported_hash_algorithm_is_rejected():
    evidence = create_evidence("PROOFRUN_SMOKE_OK\n", 0)
    evidence["hash_algorithm"] = "md5"

    assert verify_evidence("PROOFRUN_SMOKE_OK\n", evidence) is False


def test_execution_api_returns_verifiable_evidence():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    response = client.post(
        "/api/execution/run",
        json={"command": "smoke_test"},
    )

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["success"] is True
    assert "PROOFRUN_SMOKE_OK" in data["output"]
    assert verify_evidence(data["output"], data["evidence"]) is True


def test_execution_api_rejects_unsupported_command():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    response = client.post(
        "/api/execution/run",
        json={"command": "arbitrary_shell"},
    )

    assert response.status_code == 422


def test_execution_api_rejects_extra_fields():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    response = client.post(
        "/api/execution/run",
        json={
            "command": "smoke_test",
            "unexpected": "must_be_rejected",
        },
    )

    assert response.status_code == 422


def test_execution_api_rejects_missing_command():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    response = client.post(
        "/api/execution/run",
        json={},
    )

    assert response.status_code == 422


from unittest.mock import patch


def test_execution_api_returns_503_when_sandbox_fails():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.DockerRunner.run_smoke_test",
        return_value={
            "success": False,
            "error": "Simulated sandbox failure",
        },
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "smoke_test"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Sandbox execution failed"


def test_execution_api_rejects_invalid_evidence():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.verify_evidence",
        return_value=False,
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "smoke_test"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Execution evidence verification failed"
    )


def test_tampered_metadata_is_rejected():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    evidence["container_image"] = "untrusted-image:latest"

    assert verify_evidence(output, evidence) is False


def test_forged_signature_is_rejected():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    evidence["signature"] = "A" * 88

    assert verify_evidence(output, evidence) is False


def test_evidence_from_untrusted_key_is_rejected():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    untrusted_key = Ed25519PrivateKey.generate()
    untrusted_public_bytes = untrusted_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    evidence["public_key"] = base64.b64encode(
        untrusted_public_bytes
    ).decode("ascii")

    assert verify_evidence(output, evidence) is False


def test_execution_api_returns_503_when_sandbox_times_out():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.DockerRunner.run_smoke_test",
        return_value={
            "success": False,
            "error": "Sandbox execution timed out",
        },
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "smoke_test"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Sandbox execution failed"


def test_unexpected_internal_error_does_not_leak_details():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"}, raise_server_exceptions=False)

    with patch(
        "app.api.execution.DockerRunner",
        side_effect=RuntimeError("SIMULATED_INTERNAL_DETAIL"),
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "smoke_test"},
        )

    assert response.status_code == 500
    assert "SIMULATED_INTERNAL_DETAIL" not in response.text
    assert response.text == "Internal Server Error"


def test_malformed_evidence_returns_false_without_raising():
    output = "PROOFRUN_SMOKE_OK\n"

    malformed_evidence = {
        "execution_id": [],
        "timestamp": "not-a-valid-timestamp",
        "exit_code": 0,
        "container_image": "alpine:3.22",
        "output_sha256": "0" * 64,
        "hash_algorithm": "sha256",
        "signature_algorithm": "ed25519",
        "public_key": "invalid",
        "signature": "invalid",
    }

    assert verify_evidence(output, malformed_evidence) is False


def test_execution_api_hides_unexpected_internal_errors():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"}, raise_server_exceptions=False)

    with patch(
        "app.api.execution.DockerRunner",
        side_effect=RuntimeError("SIMULATED_INTERNAL_DETAIL"),
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "smoke_test"},
        )

    assert response.status_code == 500
    assert "SIMULATED_INTERNAL_DETAIL" not in response.text


def test_unexpected_evidence_field_is_rejected():
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = create_evidence(output, 0)

    evidence["admin"] = True

    assert verify_evidence(output, evidence) is False



def test_execution_api_rejects_approval_field():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    response = client.post(
        "/api/execution/run",
        json={
            "command": "smoke_test",
            "approved": True,
        },
    )

    assert response.status_code == 422

def test_containment_execution_api_returns_verifiable_evidence():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.DockerRunner.run_containment_test",
        return_value={
            "success": True,
            "exit_code": 0,
            "output": "PROOFRUN_CONTAINMENT_OK\n",
        },
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "containment_test"},
        )

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["success"] is True
    assert "PROOFRUN_CONTAINMENT_OK" in data["output"]
    assert verify_evidence(data["output"], data["evidence"]) is True


def test_containment_execution_api_returns_503_when_sandbox_fails():
    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.DockerRunner.run_containment_test",
        return_value={
            "success": False,
            "error": "Simulated containment failure",
        },
    ):
        response = client.post(
            "/api/execution/run",
            json={"command": "containment_test"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Sandbox execution failed"



def test_execution_history_rejects_tampered_output(tmp_path):
    import hashlib
    import sqlite3

    from fastapi.testclient import TestClient

    from app.main import app
    from app.storage import execution_store

    output = "PROOFRUN_SMOKE_OK\n"
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()

    db_path = tmp_path / "history.sqlite3"
    execution_store.initialize_store(db_path)

    evidence = create_evidence(output, 0)
    execution_store.save_execution(
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

    # Tamper with the persisted output after saving.
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE executions SET output = ? WHERE execution_id = ?",
            ("TAMPERED_OUTPUT\n", evidence["execution_id"]),
        )

    # Redirect the history endpoint to this isolated test database.
    original_get_execution = execution_store.get_execution

    def get_test_execution(execution_id):
        return original_get_execution(execution_id, db_path)

    from unittest.mock import patch

    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})
    with patch(
        "app.api.execution.get_execution",
        side_effect=get_test_execution,
    ):
        response = client.get(
            f"/api/execution/{evidence['execution_id']}"
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Stored execution evidence verification failed"
    )


def test_execution_history_list_rejects_tampered_output(tmp_path):
    import hashlib
    import sqlite3
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from app.storage import execution_store

    output = "PROOFRUN_SMOKE_OK\n"
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    db_path = tmp_path / "history-list.sqlite3"

    execution_store.initialize_store(db_path)
    evidence = create_evidence(output, 0)

    execution_store.save_execution(
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

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE executions SET output = ? WHERE execution_id = ?",
            ("TAMPERED_OUTPUT\n", evidence["execution_id"]),
        )

    original_list = execution_store.list_executions

    def get_test_records(*, limit=20, offset=0):
        return original_list(
            limit=limit,
            offset=offset,
            db_path=db_path,
        )

    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.list_executions",
        side_effect=get_test_records,
    ):
        response = client.get("/api/execution/")

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Stored execution evidence verification failed"
    )


def test_execution_history_list_returns_valid_verified_record(tmp_path):
    import hashlib
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from app.storage import execution_store

    output = "PROOFRUN_SMOKE_OK\n"
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    db_path = tmp_path / "valid-history.sqlite3"

    execution_store.initialize_store(db_path)
    evidence = create_evidence(output, 0)

    execution_store.save_execution(
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

    original_list = execution_store.list_executions

    def get_test_records(*, limit=20, offset=0):
        return original_list(
            limit=limit,
            offset=offset,
            db_path=db_path,
        )

    client = TestClient(app, headers={"X-API-Key": "test-proofrun-key"})

    with patch(
        "app.api.execution.list_executions",
        side_effect=get_test_records,
    ):
        response = client.get("/api/execution/")

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["count"] == 1
    record = data["items"][0]
    assert record["execution_id"] == evidence["execution_id"]
    assert record["output"] == output
    assert verify_evidence(record["output"], record["evidence"])


import copy

from app.core.evidence import create_evidence, verify_evidence


def test_evidence_rejects_modified_output():
    evidence = create_evidence("original output", 0)
    assert verify_evidence("modified output", evidence) is False


def test_evidence_rejects_modified_exit_code():
    evidence = create_evidence("original output", 0)
    tampered = copy.deepcopy(evidence)
    tampered["exit_code"] = 1

    assert verify_evidence("original output", tampered) is False


def test_evidence_rejects_modified_signature():
    evidence = create_evidence("original output", 0)
    tampered = copy.deepcopy(evidence)
    tampered["signature"] = "invalid"

    assert verify_evidence("original output", tampered) is False
