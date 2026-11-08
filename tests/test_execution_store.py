
import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import evidence as evidence_module
from app.storage.execution_store import (
    get_execution,
    initialize_store,
    list_executions,
    save_execution,
)


@pytest.fixture
def test_signer(monkeypatch):
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

    monkeypatch.setattr(
        evidence_module,
        "TRUSTED_PUBLIC_KEY",
        base64.b64encode(public_bytes).decode("ascii"),
    )
    monkeypatch.setenv(
        "PROOFRUN_ED25519_PRIVATE_KEY",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    evidence_module._load_private_key.cache_clear()

    yield evidence_module

    evidence_module._load_private_key.cache_clear()


def test_execution_output_is_persisted(tmp_path, test_signer):
    db_path = tmp_path / "executions.sqlite3"
    initialize_store(db_path)

    output = "PROOFRUN_SMOKE_OK\n"
    evidence = test_signer.create_evidence(output, 0)

    save_execution(
        execution_id=evidence["execution_id"],
        timestamp=evidence["timestamp"],
        command="smoke_test",
        exit_code=0,
        output=output,
        output_sha256=evidence["output_sha256"],
        evidence=evidence,
        verified=True,
        db_path=db_path,
    )

    record = get_execution(evidence["execution_id"], db_path)

    assert record is not None
    assert record["output"] == output
    assert record["output_sha256"] == evidence["output_sha256"]
    assert test_signer.verify_evidence(record["output"], record["evidence"])


def test_execution_output_hash_mismatch_is_rejected(
    tmp_path, test_signer
):
    db_path = tmp_path / "hash-mismatch.sqlite3"
    initialize_store(db_path)

    output = "TAMPERED_OUTPUT"
    evidence = test_signer.create_evidence("ORIGINAL_OUTPUT", 0)

    with pytest.raises(ValueError, match="does not match"):
        save_execution(
            execution_id=evidence["execution_id"],
            timestamp=evidence["timestamp"],
            command="smoke_test",
            exit_code=0,
            output=output,
            output_sha256=evidence["output_sha256"],
            evidence=evidence,
            verified=True,
            db_path=db_path,
        )


def test_execution_history_pagination_returns_newest_first(
    tmp_path, test_signer
):
    db_path = tmp_path / "pagination.sqlite3"
    initialize_store(db_path)

    execution_ids = []

    for index in range(3):
        output = f"EXECUTION_{index}\n"
        evidence = test_signer.create_evidence(output, 0)
        timestamp = f"2026-10-19T00:00:0{index}+00:00"

        # Update the timestamp and sign the modified evidence again.
        evidence["timestamp"] = timestamp
        evidence["signature"] = base64.b64encode(
            test_signer._load_private_key().sign(
                test_signer._canonical_payload(evidence)
            )
        ).decode("ascii")

        execution_ids.append(evidence["execution_id"])

        save_execution(
            execution_id=evidence["execution_id"],
            timestamp=timestamp,
            command="smoke_test",
            exit_code=0,
            output=output,
            output_sha256=evidence["output_sha256"],
            evidence=evidence,
            verified=True,
            db_path=db_path,
        )

    first_page = list_executions(limit=2, offset=0, db_path=db_path)
    second_page = list_executions(limit=2, offset=2, db_path=db_path)

    assert [r["execution_id"] for r in first_page] == [
        execution_ids[2],
        execution_ids[1],
    ]
    assert [r["execution_id"] for r in second_page] == [
        execution_ids[0],
    ]

    for record in first_page + second_page:
        assert test_signer.verify_evidence(
            record["output"], record["evidence"]
        )


def test_store_rejects_evidence_with_mismatched_execution_id(
    tmp_path, test_signer
):
    output = "PROOFRUN_SMOKE_OK\n"
    evidence = test_signer.create_evidence(output, 0)

    with pytest.raises(
        ValueError,
        match="Evidence execution ID does not match",
    ):
        save_execution(
            execution_id="different-execution-id",
            timestamp=evidence["timestamp"],
            command="smoke_test",
            exit_code=0,
            output=output,
            output_sha256=evidence["output_sha256"],
            evidence=evidence,
            verified=True,
            db_path=tmp_path / "mismatch.sqlite3",
        )
