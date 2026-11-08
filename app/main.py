from pathlib import Path
from dotenv import load_dotenv
from app.core.security_middleware import ProofRunSecurityMiddleware
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, encoding="utf-8-sig")

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from app.core.evidence import TRUSTED_PUBLIC_KEY

_private = os.environ.get("PROOFRUN_ED25519_PRIVATE_KEY")

if not _private:
    raise RuntimeError("ProofRun signing key is missing")

_key = Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(_private, validate=True)
)

_actual_public = _key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

_expected_public = base64.b64decode(
    TRUSTED_PUBLIC_KEY,
    validate=True,
)

if _actual_public != _expected_public:
    raise RuntimeError("ProofRun signing key does not match trusted key")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.execution import router as execution_router
from app.api.agent import router as agent_router


app = FastAPI(
    title="ProofRun",
    description="Verifiable, sandboxed AI agent execution",
    version="0.1.0",
)
app.add_middleware(ProofRunSecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-API-Key",
    ],
)

app.include_router(health_router)
app.include_router(execution_router)
app.include_router(agent_router)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ProofRun"}


@app.get("/")
def root():
    return {
        "name": "ProofRun",
        "message": "Secure AI execution with verifiable evidence",
    }
