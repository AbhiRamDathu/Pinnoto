import base64
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import evidence as evidence_module
import pytest


@pytest.fixture(autouse=True)
def configure_test_api_key(monkeypatch):
    monkeypatch.setenv(
        "PROOFRUN_API_KEY",
        "test-proofrun-key",
    )

@pytest.fixture(autouse=True)
def test_signing_configuration(monkeypatch):
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

    encoded_private = base64.b64encode(private_bytes).decode("ascii")
    encoded_public = base64.b64encode(public_bytes).decode("ascii")

    monkeypatch.setenv(
        "PROOFRUN_ED25519_PRIVATE_KEY",
        encoded_private,
    )
    monkeypatch.setattr(
        evidence_module,
        "TRUSTED_PUBLIC_KEY",
        encoded_public,
    )

    evidence_module._load_private_key.cache_clear()
    yield
    evidence_module._load_private_key.cache_clear()


import base64

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.core import evidence as evidence_module
from app.core.security_middleware import _requests, _rate_lock


@pytest.fixture(autouse=True)
def configure_test_api_key(monkeypatch):
    monkeypatch.setenv(
        "PROOFRUN_API_KEY",
        "test-proofrun-key",
    )


@pytest.fixture(autouse=True)
def test_signing_configuration(monkeypatch):
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

    encoded_private = base64.b64encode(private_bytes).decode("ascii")
    encoded_public = base64.b64encode(public_bytes).decode("ascii")

    monkeypatch.setenv(
        "PROOFRUN_ED25519_PRIVATE_KEY",
        encoded_private,
    )

    monkeypatch.setattr(
        evidence_module,
        "TRUSTED_PUBLIC_KEY",
        encoded_public,
    )

    evidence_module._load_private_key.cache_clear()

    yield

    evidence_module._load_private_key.cache_clear()


@pytest.fixture(autouse=True)
def isolate_rate_limit_state():
    """Prevent rate-limit state leaking between tests."""

    with _rate_lock:
        _requests.clear()

    yield

    with _rate_lock:
        _requests.clear()
