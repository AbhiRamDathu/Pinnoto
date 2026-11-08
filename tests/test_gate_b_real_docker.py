import base64
import hashlib
import sqlite3

import docker
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.core import execution_service, evidence
from app.storage.execution_store import get_execution


def test_real_docker_verified_execution_chain(tmp_path, monkeypatch):
    db_path = tmp_path / "real_docker_gate_b.sqlite3"

    client = docker.from_env()
    try:
        client.ping()
    except Exception as exc:
        client.close()
        pytest.skip(
            f"Docker daemon unavailable; real integration not run: "
            f"{type(exc).__name__}"
        )

    try:
        # Snapshot existing ProofRun containers to avoid confusing
        # unrelated pre-existing containers with this test's cleanup.
        before_ids = {
            item.id
            for item in client.containers.list(
                all=True, filters={"label": "app=proofrun"}
            )
        }

        test_key = Ed25519PrivateKey.generate()
        private_bytes = test_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = test_key.public_key().public_bytes(
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
        evidence._load_private_key.cache_clear()

        monkeypatch.setattr(
            execution_service, "create_evidence", evidence.create_evidence
        )
        monkeypatch.setattr(
            execution_service, "verify_evidence", evidence.verify_evidence
        )

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
            execution_service, "save_execution", save_to_test_db
        )

        # No FakeRunner here: invoke the actual DockerRunner.
        result = execution_service.run_verified_smoke_test(
            runner_factory=execution_service.DockerRunner,
        )

        assert result["success"] is True
        assert isinstance(result["output"], str)
        assert result["output"].strip()
        assert result["evidence"]["exit_code"] == 0

        output = result["output"]
        signed_evidence = result["evidence"]

        assert evidence.verify_evidence(output, signed_evidence)
        assert signed_evidence["output_sha256"] == hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest()

        record = get_execution(
            signed_evidence["execution_id"], db_path=db_path
        )
        assert record is not None
        assert record["verified"] is True
        assert record["exit_code"] == 0
        assert record["output"] == output
        assert record["evidence"] == signed_evidence

        with sqlite3.connect(db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM executions WHERE execution_id = ?",
                (signed_evidence["execution_id"],),
            ).fetchone()[0]

        assert count == 1

        after_ids = {
            item.id
            for item in client.containers.list(
                all=True, filters={"label": "app=proofrun"}
            )
        }
        assert after_ids.issubset(before_ids), (
            "New ProofRun containers remain after execution."
        )

    finally:
        evidence._load_private_key.cache_clear()
        client.close()
