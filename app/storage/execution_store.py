
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from contextlib import closing
import hashlib
import hmac
from app.core.evidence import verify_evidence

DEFAULT_DB_PATH = Path(
    os.getenv(
        "PROOFRUN_DB_PATH",
        str(Path.home() / ".proofrun" / "executions.sqlite3"),
    )
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL
        CHECK (command IN ('smoke_test', 'containment_test')),
    exit_code INTEGER NOT NULL,
    output TEXT,
    output_sha256 TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    verified INTEGER NOT NULL
        CHECK (verified IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_executions_timestamp
ON executions(timestamp);
"""


class ExecutionStoreError(Exception):
    """Safe error raised by the execution persistence layer."""


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path = path.expanduser().resolve()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise ExecutionStoreError(
            "Execution storage is unavailable."
        ) from exc



def initialize_store(db_path: str | Path | None = None) -> None:
    """Create the history table and migrate older databases."""
    try:
        with closing(_connect(db_path)) as connection:
            with connection:
                connection.executescript(SCHEMA)
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(executions)"
                    )
                }
                if "output" not in columns:
                    connection.execute(
                        "ALTER TABLE executions ADD COLUMN output TEXT"
                    )
    except ExecutionStoreError:
        raise
    except sqlite3.Error as exc:
        raise ExecutionStoreError(
            "Execution storage initialization failed."
        ) from exc


def save_execution(
    *,
    execution_id: str,
    timestamp: str,
    command: str,
    exit_code: int,
    output: str,
    output_sha256: str,
    evidence: dict[str, Any],
    verified: bool,
    db_path: str | Path | None = None,
) -> None:
    """Persist metadata for an execution with verified evidence."""
    if command not in {"smoke_test", "containment_test"}:
        raise ValueError("Unsupported execution command.")

    if verified is not True:
        raise ValueError("Only verified executions may be stored.")

    if not execution_id or not timestamp:
        raise ValueError("Execution ID and timestamp are required.")

    if (
        not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or exit_code != 0
    ):
        raise ValueError("Only successful executions may be stored.")

    if (
        not isinstance(output_sha256, str)
        or len(output_sha256) != 64
        or any(c not in "0123456789abcdef" for c in output_sha256)
    ):
        raise ValueError("A valid SHA-256 digest is required.")

    if not isinstance(evidence, dict):
        raise ValueError("Evidence must be an object.")

        
    if evidence.get("execution_id") != execution_id:
        raise ValueError("Evidence execution ID does not match.")

    if evidence.get("timestamp") != timestamp:
        raise ValueError("Evidence timestamp does not match.")

    if evidence.get("exit_code") != exit_code:
        raise ValueError("Evidence exit code does not match.")

    if evidence.get("output_sha256") != output_sha256:
        raise ValueError("Evidence output hash does not match.")


    if not isinstance(output, str):
        raise ValueError("Execution output must be a string.")

    actual_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()

    if not hmac.compare_digest(actual_hash, output_sha256):
        raise ValueError("Output does not match its SHA-256 digest.")

    if not verify_evidence(output, evidence):
        raise ValueError("Execution evidence verification failed.")

    try:
        initialize_store(db_path)

        evidence_json = json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        )

        with closing(_connect(db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO executions (
                        execution_id, timestamp, command, exit_code,
                        output, output_sha256, evidence_json, verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        execution_id,
                        timestamp,
                        command,
                        exit_code,
                        output,
                        output_sha256,
                        evidence_json,
                        1,
                    ),
                )
    except ExecutionStoreError:
        raise
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise ExecutionStoreError(
            "Execution record could not be saved."
        ) from exc


def get_execution(
    execution_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Retrieve a single execution by its unique ID."""
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise ValueError("Execution ID is required.")

    try:
        initialize_store(db_path)

        with closing(_connect(db_path)) as connection:
            with connection:
                row = connection.execute(
                """
                SELECT execution_id, timestamp, command, exit_code, output,
                       output_sha256, evidence_json, verified
                FROM executions
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

        if row is None:
            return None

        record = dict(row)
        record["evidence"] = json.loads(record.pop("evidence_json"))
        record["verified"] = bool(record["verified"])
        return record

    except ExecutionStoreError:
        raise
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise ExecutionStoreError(
            "Execution record could not be retrieved."
        ) from exc


def list_executions(
    *,
    limit: int = 20,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return recent execution records, newest first."""
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        raise ValueError("Limit must be between 1 and 100.")

    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise ValueError("Offset must be non-negative.")

    try:
        initialize_store(db_path)

        with closing(_connect(db_path)) as connection:
            with connection:
                rows = connection.execute(
                """
                SELECT execution_id, timestamp, command, exit_code, output,
                       output_sha256, evidence_json, verified
                FROM executions
                ORDER BY timestamp DESC, execution_id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        records = []
        for row in rows:
            record = dict(row)
            record["evidence"] = json.loads(
                record.pop("evidence_json")
            )
            record["verified"] = bool(record["verified"])
            records.append(record)

        return records

    except ExecutionStoreError:
        raise
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise ExecutionStoreError(
            "Execution history could not be retrieved."
        ) from exc
