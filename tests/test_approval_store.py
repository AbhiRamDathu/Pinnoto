
import concurrent.futures
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from app.storage.approval_store import (
    initialize_approval_store,
    save_approval,
    consume_approval,
)


def make_approval(db_path, approval_id="approval-001"):
    plan = {
        "summary": "Run approved smoke test",
        "actions": ["smoke_test"],
    }

    plan_hash = hashlib.sha256(
        json.dumps(
            plan,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    save_approval(
        approval_id=approval_id,
        plan=plan,
        plan_hash=plan_hash,
        expires_at=2000.0,
        created_at="2026-10-30T07:00:00Z",
        db_path=db_path,
    )

    return plan, plan_hash


def test_approval_persists_across_connections(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"

    initialize_approval_store(db_path)

    plan, plan_hash = make_approval(db_path)

    result = consume_approval(
        approval_id="approval-001",
        plan_hash=plan_hash,
        now=1000.0,
        db_path=db_path,
    )

    assert result is not None
    assert result["plan"] == plan
    assert result["plan_hash"] == plan_hash


def test_approval_can_only_be_consumed_once(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"

    _, plan_hash = make_approval(db_path)

    first = consume_approval(
        approval_id="approval-001",
        plan_hash=plan_hash,
        now=1000.0,
        db_path=db_path,
    )

    second = consume_approval(
        approval_id="approval-001",
        plan_hash=plan_hash,
        now=1000.0,
        db_path=db_path,
    )

    assert first is not None
    assert second is None


def test_expired_approval_is_rejected(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"

    _, plan_hash = make_approval(db_path)

    result = consume_approval(
        approval_id="approval-001",
        plan_hash=plan_hash,
        now=2000.0,
        db_path=db_path,
    )

    assert result is None


def test_wrong_plan_hash_is_rejected_without_consuming(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"

    _, correct_hash = make_approval(db_path)

    wrong_hash = "0" * 64

    result = consume_approval(
        approval_id="approval-001",
        plan_hash=wrong_hash,
        now=1000.0,
        db_path=db_path,
    )

    assert result is None

    retry = consume_approval(
        approval_id="approval-001",
        plan_hash=correct_hash,
        now=1000.0,
        db_path=db_path,
    )

    assert retry is not None


def test_concurrent_consumption_only_succeeds_once(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"

    _, plan_hash = make_approval(db_path)

    workers = 10
    barrier = threading.Barrier(workers)

    def consume():
        barrier.wait()

        return consume_approval(
            approval_id="approval-001",
            plan_hash=plan_hash,
            now=1000.0,
            db_path=db_path,
        )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers
    ) as executor:
        results = list(executor.map(
            lambda _: consume(),
            range(workers),
        ))

    successful = [result for result in results if result is not None]

    assert len(successful) == 1

def test_approval_can_only_be_consumed_once_concurrently(tmp_path):
    db_path = tmp_path / "concurrent_approvals.db"

    initialize_approval_store(db_path)

    approval_id = "concurrent-approval-test"
    plan_hash = "a" * 64

    save_approval(
        approval_id=approval_id,
        plan={"action": "smoke_test"},
        plan_hash=plan_hash,
        expires_at=2000.0,
        created_at="2026-10-30T00:00:00Z",
        db_path=db_path,
    )

    workers = 8
    barrier = Barrier(workers)

    def consume():
        barrier.wait(timeout=10)

        return consume_approval(
            approval_id=approval_id,
            plan_hash=plan_hash,
            now=1000.0,
            db_path=db_path,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda _: consume(), range(workers)))

    successful = [result for result in results if result is not None]

    assert len(successful) == 1
    assert successful[0]["approval_id"] == approval_id

    # A consumed approval must not be available again.
    assert consume_approval(
        approval_id=approval_id,
        plan_hash=plan_hash,
        now=1000.0,
        db_path=db_path,
    ) is None