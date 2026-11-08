
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.storage.execution_store import (
    DEFAULT_DB_PATH,
    ExecutionStoreError,
    _connect,
)


class ApprovalStoreError(Exception):
    """Safe error raised by persistent approval storage."""


def initialize_approval_store(
    db_path: str | Path | None = None,
) -> None:
    try:
        with closing(_connect(db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_approvals (
                        approval_id TEXT PRIMARY KEY,
                        plan_json TEXT NOT NULL,
                        plan_hash TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_pending_approvals_expiry
                    ON pending_approvals(expires_at)
                    """
                )

    except (ExecutionStoreError, sqlite3.Error) as exc:
        raise ApprovalStoreError(
            "Approval storage initialization failed."
        ) from exc


def save_approval(
    *,
    approval_id: str,
    plan: dict[str, Any],
    plan_hash: str,
    expires_at: float,
    created_at: str,
    db_path: str | Path | None = None,
) -> None:
    if not approval_id or not isinstance(approval_id, str):
        raise ValueError("Approval ID is required.")

    if not isinstance(plan, dict):
        raise ValueError("Approval plan must be an object.")

    if (
        not isinstance(plan_hash, str)
        or len(plan_hash) != 64
        or any(c not in "0123456789abcdef" for c in plan_hash)
    ):
        raise ValueError("Invalid plan hash.")

    if not isinstance(expires_at, (int, float)) or isinstance(
        expires_at, bool
    ):
        raise ValueError("Invalid approval expiry.")

    if not isinstance(created_at, str) or not created_at:
        raise ValueError("Creation timestamp is required.")

    try:
        initialize_approval_store(db_path)

        plan_json = json.dumps(
            plan,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        with closing(_connect(db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO pending_approvals (
                        approval_id,
                        plan_json,
                        plan_hash,
                        expires_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id,
                        plan_json,
                        plan_hash,
                        float(expires_at),
                        created_at,
                    ),
                )

    except (ExecutionStoreError, sqlite3.Error, TypeError) as exc:
        raise ApprovalStoreError(
            "Approval could not be stored."
        ) from exc


def consume_approval(
    *,
    approval_id: str,
    plan_hash: str,
    now: float,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    if not isinstance(approval_id, str) or not approval_id:
        raise ValueError("Approval ID is required.")

    if (
        not isinstance(plan_hash, str)
        or len(plan_hash) != 64
        or any(c not in "0123456789abcdef" for c in plan_hash)
    ):
        raise ValueError("Invalid plan hash.")

    if not isinstance(now, (int, float)) or isinstance(now, bool):
        raise ValueError("Invalid current time.")

    try:
        initialize_approval_store(db_path)

        with closing(_connect(db_path)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")

                row = connection.execute(
                    """
                    SELECT approval_id, plan_json, plan_hash,
                           expires_at, created_at
                    FROM pending_approvals
                    WHERE approval_id = ?
                    """,
                    (approval_id,),
                ).fetchone()

                if row is None:
                    return None

                if row["expires_at"] <= now:
                    connection.execute(
                        """
                        DELETE FROM pending_approvals
                        WHERE approval_id = ?
                        """,
                        (approval_id,),
                    )
                    return None

                import hmac

                if not hmac.compare_digest(
                    row["plan_hash"],
                    plan_hash,
                ):
                    return None

                connection.execute(
                    """
                    DELETE FROM pending_approvals
                    WHERE approval_id = ?
                    """,
                    (approval_id,),
                )

                return {
                    "approval_id": row["approval_id"],
                    "plan": json.loads(row["plan_json"]),
                    "plan_hash": row["plan_hash"],
                    "expires_at": row["expires_at"],
                    "created_at": row["created_at"],
                }

    except (ExecutionStoreError, sqlite3.Error, ValueError, TypeError) as exc:
        raise ApprovalStoreError(
            "Approval could not be consumed."
        ) from exc
