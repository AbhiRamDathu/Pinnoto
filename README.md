# ProofRun

**Verifiable, sandboxed execution for AI agents.**

ProofRun is a FastAPI-based execution and evidence-verification service designed to help AI agents perform controlled work and produce cryptographically verifiable results.

The project combines Docker-based execution isolation, SHA-256 output integrity checks, Ed25519 digital signatures, trusted-key verification, and automated tests.

> **Project status:** Active development. The latest reported full test-suite checkpoint is **87 passed in 5.39 seconds**. This verifies the reported automated tests, not production readiness or a complete security audit.

## Current capabilities

- FastAPI execution API with request validation and health checks.
- Predefined Docker smoke-test execution through the execution API.
- Bounded Python execution through the `CodeRunner` component, with code-size and output-size limits.
- Docker execution configuration requesting network isolation, read-only root filesystems, dropped Linux capabilities, non-root execution, and CPU, memory, and PID limits.
- Execution timeout handling and container cleanup.
- SHA-256 output-integrity verification.
- Ed25519 signatures for execution evidence.
- Verification against a trusted public key.
- Detection of tampered output, altered metadata, invalid signatures, and untrusted signing keys, as covered by the existing tests.
- Persistent execution records and API workflows, subject to the existing storage and verification rules.
- Automated regression tests for execution, evidence verification, API behavior, storage, and sandbox configuration.

**Integration boundary:** The existence of the bounded Python runner does not, by itself, establish that arbitrary Python execution is exposed through the public API or connected to an AI planning agent. That end-to-end integration must be verified separately.

## Architecture

The intended execution workflow is:

1. **Request validation** — Validate the incoming task and its permitted operation.
2. **Authorization** — Apply the execution policy before allowing work to run.
3. **Sandbox execution** — Run the approved task inside a restricted Docker container.
4. **Result collection** — Collect the exit status and bounded execution output.
5. **Evidence generation** — Hash the output and create signed execution evidence.
6. **Independent verification** — Validate the evidence against a trusted public key and the expected execution metadata.
7. **Persistence** — Store records only when the applicable verification and storage requirements are satisfied.

The complete workflow should be verified through integration tests before being described as fully operational.

## Technology stack

- Python 3.12
- FastAPI
- Uvicorn
- Docker Engine
- Docker SDK for Python
- Pydantic
- `cryptography`
- `pytest`
- `httpx` for HTTP-based API tests, if confirmed by the project's dependency files

## Prerequisites

- Python 3.12
- Docker Desktop on Windows or a compatible Docker Engine
- A running Docker daemon accessible to the Python Docker SDK
- PowerShell on Windows or an equivalent terminal

Verify Docker availability before testing container execution.

```powershell
docker version
docker info
```

Both commands should succeed against the intended Docker daemon.

## Local setup

From the project root, create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If using the pinned dependency file:

```powershell
python -m pip install -r requirements-lock.txt
```

### Reproducible dependencies

- `requirements.txt` defines the project's direct dependencies.
- `requirements-lock.txt` is intended to capture pinned dependency versions.
- The latest reported test checkpoint was run in the `.venv-lockcheck` environment.

A passing test suite in an existing virtual environment does not independently prove that installation succeeds from scratch. Validate the lock file in a fresh environment before claiming clean-install reproducibility.

## Configuration and signing keys

Configure the Ed25519 private signing key using the application's expected configuration mechanism.

If the application uses a local `.env` file, the expected setting is:

```text
PROOFRUN_ED25519_PRIVATE_KEY=<BASE64_ENCODED_PRIVATE_KEY>
```

The value must match the encoding and key format expected by the implementation.

**Never commit `.env` files, private keys, API credentials, or other secrets.**

The verifier must trust a public key obtained through a trusted configuration channel. It must not trust a public key merely because the evidence payload supplies it.

If the trusted public key is currently hardcoded in `app/core/evidence.py`, ensure that the configured private key corresponds to that public key. Production key provisioning, rotation, and access control require additional operational safeguards.

## Run the tests

Activate the intended virtual environment and run the complete suite:

```powershell
.\.venv-lockcheck\Scripts\python.exe -m pytest -q
```

To run the focused execution and evidence tests:

```powershell
.\.venv-lockcheck\Scripts\python.exe -m pytest tests\test_code_runner.py -q
.\.venv-lockcheck\Scripts\python.exe -m pytest tests\test_execution_api.py tests\test_execution_store.py -q
.\.venv-lockcheck\Scripts\python.exe -m pytest tests\test_evidence.py -q
.\.venv-lockcheck\Scripts\python.exe -m pytest tests\test_docker_runner.py -q
```

### Latest reported verification checkpoint

| Test group | Result |
|---|---|
| CodeRunner unit tests | 6 passed |
| Full regression suite | 87 passed in 5.39 seconds |

These results were reported from the development environment. Re-run the tests after changes and update this section with the actual results.

## Start the API

From the project root, with the virtual environment activated:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Interactive API documentation:

<http://127.0.0.1:8000/docs>

Health endpoint:

```http
GET /health
```

Check the actual route definitions in the running application if an endpoint differs from this documentation.

## Execution smoke test

The execution API supports the predefined `smoke_test` command, according to the current API contract.

Submit a request to:

```http
POST /api/execution/run
Content-Type: application/json
```

Request body:

```json
{
  "command": "smoke_test"
}
```

A successful response is expected to include execution results and evidence, according to the endpoint's response model.

The public API's supported commands must be distinguished from the internal `CodeRunner` capability. Do not assume that arbitrary Python source code can be submitted through the public API unless the route and authorization logic explicitly support it.

## Security model and limitations

ProofRun requests several container-level security controls:

- Network isolation.
- Read-only root filesystem.
- Dropped Linux capabilities.
- Non-root container execution.
- CPU, memory, and process-count limits.
- Bounded code input and captured output in the Python runner.
- Execution timeout handling and container cleanup.

These controls reduce the available attack surface but do not establish that the sandbox is immune to escape or denial-of-service attacks.

### Evidence integrity

- **SHA-256** detects changes to the hashed output.
- **Ed25519** authenticates evidence signed by the corresponding private key.
- **Trusted-key verification** helps prevent acceptance of evidence signed by an untrusted key.
- **Metadata validation** checks that the signed information matches the expected execution record.

A valid signature proves that the signed payload was signed by the corresponding private key. It does not, by itself, prove that the reported task actually executed correctly or that the execution environment was uncompromised.

### Validation still required

Before making stronger security claims, validate:

- Real Docker execution and cleanup, including timeout and daemon-failure scenarios.
- Network isolation and resource limits in a running container.
- Rejection of unauthorized or malformed execution requests.
- Independent evidence verification and persistence behavior.
- End-to-end integration between planning, authorization, execution, and evidence.
- Deployment configuration, authentication, rate limiting, monitoring, and secret management.

Unit tests that inspect Docker SDK arguments are useful, but they do not independently prove that every restriction is enforced by the runtime.

## Project status and roadmap

ProofRun is under active development.

The next priorities are:

1. Validate sandbox behavior using real-container integration tests.
2. Verify the end-to-end execution and evidence pipeline.
3. Confirm that planning and execution are connected through explicit authorization and validation.
4. Validate reproducible installation and deployment.
5. Integrate Vultr and inference services when credentials, infrastructure access, and hackathon resources are available.
6. Document measured results and security limitations accurately.

Vultr API integration and production deployment should be considered incomplete until demonstrated and tested.

## Hackathon preparation

Before submission, verify the official challenge requirements, judging criteria, infrastructure rules, reproducibility requirements, and evidence expectations.

Document demonstrated capabilities separately from planned capabilities. Include test commands and actual results, explain the threat model, and provide reproducible instructions for running the project.

**ProofRun's goal is to make agent execution controlled, auditable, and verifiable—not merely to report that a command succeeded.**
