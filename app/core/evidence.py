
import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

TRUSTED_PUBLIC_KEY = "dHMzRBBlduYnVpmWQDk9BddR5fJnS0O/pQqf/NAB1xA="

DEFAULT_IMAGE = (
    "alpine:3.22@sha256:"
    "5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8"
)


def _canonical_payload(evidence: dict) -> bytes:
    fields = {
        "execution_id": evidence["execution_id"],
        "timestamp": evidence["timestamp"],
        "exit_code": evidence["exit_code"],
        "container_image": evidence["container_image"],
        "output_sha256": evidence["output_sha256"],
        "hash_algorithm": evidence["hash_algorithm"],
        "signature_algorithm": evidence["signature_algorithm"],
        "public_key": evidence["public_key"],
    }
    return json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@lru_cache(maxsize=1)
def _load_private_key() -> Ed25519PrivateKey:
    encoded = os.environ.get("PROOFRUN_ED25519_PRIVATE_KEY")
    if not encoded:
        raise RuntimeError(
            "PROOFRUN_ED25519_PRIVATE_KEY is not configured"
        )

    try:
        key_bytes = base64.b64decode(encoded, validate=True)
        return Ed25519PrivateKey.from_private_bytes(key_bytes)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Invalid Ed25519 private key") from exc


def create_evidence(
    output: str,
    exit_code: int,
    image: str = DEFAULT_IMAGE,
) -> dict:
    output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    private_key = _load_private_key()
    public_key = private_key.public_key()

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    evidence = {
        "execution_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "container_image": image,
        "output_sha256": output_hash,
        "hash_algorithm": "sha256",
        "signature_algorithm": "ed25519",
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
    }

    signature = private_key.sign(_canonical_payload(evidence))
    evidence["signature"] = base64.b64encode(signature).decode("ascii")
    return evidence


def verify_evidence(output: str, evidence: dict) -> bool:
    if not isinstance(evidence, dict) or not isinstance(output, str):
        return False

    expected_fields = {
        "execution_id",
        "timestamp",
        "exit_code",
        "container_image",
        "output_sha256",
        "hash_algorithm",
        "signature_algorithm",
        "public_key",
        "signature",
    }
    if set(evidence) != expected_fields:
        return False


    try:
        if evidence.get("hash_algorithm") != "sha256":
            return False
        if evidence.get("signature_algorithm") != "ed25519":
            return False

        expected_hash = evidence.get("output_sha256")
        if not isinstance(expected_hash, str):
            return False

        actual_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            return False
        public_bytes = base64.b64decode(
            evidence["public_key"], validate=True
        )

        trusted_public_bytes = base64.b64decode(
            TRUSTED_PUBLIC_KEY, validate=True
        )

        if not hmac.compare_digest(public_bytes, trusted_public_bytes):
            return False

        signature = base64.b64decode(
            evidence["signature"], validate=True
        )
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)

        signature = base64.b64decode(
            evidence["signature"], validate=True
        )
        public_key.verify(signature, _canonical_payload(evidence))
        return True

    except (
        InvalidSignature,
        ValueError,
        TypeError,
        KeyError,
    ):
        return False
