import base64
import hashlib
import json
import sqlite3

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.core import execution_service, evidence
from app.storage.execution_store import get_execution


def test_full_verified_execution_chain(tmp_path, monkeypatch):
    db_path = tmp_path / "gate_b.sqlite3"

    # Generate an isolated signing key for this test only.
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
        evidence,
        "TRUSTED_PUBLIC_KEY",
        base64.b64encode(public_bytes).decode("ascii"),
    )

    # Clear the cached key so it reads the test-only environment variable.
    evidence._load_private_key.cache_clear()

    monkeypatch.setattr(
        execution_service,
        "create_evidence",
        evidence.create_evidence,
    )
    monkeypatch.setattr(
        execution_service,
        "verify_evidence",
        evidence.verify_evidence,
    )

    # Preserve the original functions before patching.
    original_initialize = execution_service.initialize_store
    original_save = execution_service.save_execution

    monkeypatch.setattr(
        execution_service,
        "initialize_store",
        lambda: original_initialize(db_path),
    )

    def save_to_test_db(**kwargs):
        return original_save(**kwargs, db_path=db_path)

    monkeypatch.setattr(
        execution_service,
        "save_execution",
        save_to_test_db,
    )

    class FakeRunner:
        def run_smoke_test(self):
            return {
                "success": True,
                "exit_code": 0,
                "output": "PROOFRUN_GATE_B_E2E_OK",
            }

    try:
        result = execution_service.run_verified_smoke_test(
            runner_factory=FakeRunner,
        )

        assert result["success"] is True
        assert result["output"] == "PROOFRUN_GATE_B_E2E_OK"

        output = result["output"]
        signed_evidence = result["evidence"]

        assert evidence.verify_evidence(output, signed_evidence)
        assert signed_evidence["output_sha256"] == hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest()

        record = get_execution(
            signed_evidence["execution_id"],
            db_path=db_path,
        )

        assert record is not None
        assert record["verified"] is True
        assert record["exit_code"] == 0
        assert record["output"] == output
        assert record["evidence"] == signed_evidence
        assert record["output_sha256"] == signed_evidence["output_sha256"]

        with sqlite3.connect(db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM executions WHERE execution_id = ?",
                (signed_evidence["execution_id"],),
            ).fetchone()[0]

        assert count == 1

    finally:
        evidence._load_private_key.cache_clear()
