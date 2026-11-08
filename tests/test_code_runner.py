from unittest.mock import MagicMock
from requests.exceptions import ReadTimeout
from app.sandbox.code_runner import CodeRunner


def test_rejects_empty_code():
    runner = CodeRunner(client=MagicMock())

    result = runner.run_python("  ")

    assert result["success"] is False
    assert "empty" in result["error"]


def test_rejects_oversized_code():
    runner = CodeRunner(client=MagicMock())

    result = runner.run_python("x" * 8001)

    assert result["success"] is False
    assert "size limit" in result["error"]


def test_valid_code_starts_restricted_container():
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"HELLO_PROOFRUN\n"

    runner = CodeRunner(client=client)
    result = runner.run_python('print("HELLO_PROOFRUN")')

    assert result["success"] is True
    assert "HELLO_PROOFRUN" in result["output"]

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["network_disabled"] is True
    assert kwargs["read_only"] is True
    assert kwargs["mem_limit"] == "128m"
    assert kwargs["pids_limit"] == 32

def test_timeout_kills_and_removes_container():
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.side_effect = ReadTimeout("timeout")

    runner = CodeRunner(client=client)
    result = runner.run_python("while True: pass")

    assert result["success"] is False
    assert "timed out" in result["error"].lower()
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_output_over_limit_is_marked_truncated():
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"A" * 16_385

    runner = CodeRunner(client=client)
    result = runner.run_python('print("A")')

    assert result["success"] is False
    assert result["output_truncated"] is True
    assert len(result["output"].encode("utf-8")) == 16_384


def test_timeout_still_attempts_container_removal():
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.side_effect = ReadTimeout("timeout")
    container.kill.side_effect = Exception("simulated kill failure")

    runner = CodeRunner(client=client)
    result = runner.run_python("while True: pass")

    assert result["success"] is False
    container.remove.assert_called_once_with(force=True)


import time
import uuid

import docker

from app.sandbox.code_runner import CodeRunner



def test_real_code_runner_timeout_and_cleanup():
    import time
    import uuid

    import docker
    import pytest
    from docker.errors import NotFound

    from app.sandbox.code_runner import CodeRunner

    client = docker.from_env()
    marker = f"proofrun-timeout-{uuid.uuid4().hex}"

    class MarkedCodeRunner(CodeRunner):
        def run_python(self, code: str) -> dict:
            # Attach a unique label to this specific execution.
            original_run = self.client.containers.run

            def labeled_run(*args, **kwargs):
                labels = dict(kwargs.get("labels") or {})
                labels["proofrun.test.marker"] = marker
                kwargs["labels"] = labels
                return original_run(*args, **kwargs)

            self.client.containers.run = labeled_run
            try:
                return super().run_python(code)
            finally:
                self.client.containers.run = original_run

    try:
        started = time.monotonic()
        result = MarkedCodeRunner(client=client).run_python(
            "import time\nwhile True: time.sleep(0.1)"
        )
        elapsed = time.monotonic() - started

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert elapsed < 20

        remaining = client.containers.list(
            all=True,
            filters={"label": f"proofrun.test.marker={marker}"},
        )
        assert remaining == [], (
            "The timeout execution container still exists."
        )
    finally:
        client.close()


def test_real_code_runner_success():
    client = docker.from_env()

    try:
        result = CodeRunner(client=client).run_python(
            "print('PROOFRUN_CODE_OK')"
        )

        assert result["success"] is True
        assert "PROOFRUN_CODE_OK" in result["output"]
    finally:
        client.close()

def test_transport_failure_still_removes_container():
    from requests.exceptions import ConnectionError

    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.side_effect = ConnectionError("transport failure")

    result = CodeRunner(client=client).run_python("print('test')")

    assert result["success"] is False
    container.remove.assert_called_once_with(force=True)


def test_cleanup_failure_does_not_escape():
    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"OK"
    container.kill.side_effect = Exception("kill failed")
    container.remove.side_effect = Exception("remove failed")

    result = CodeRunner(client=client).run_python("print('OK')")

    assert result["success"] is True
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)

def test_docker_api_error_during_wait_still_cleans_up():
    from docker.errors import APIError

    client = MagicMock()
    container = client.containers.run.return_value

    container.wait.side_effect = APIError(
        "simulated Docker API failure"
    )

    result = CodeRunner(client=client).run_python(
        "print('test')"
    )

    assert result["success"] is False
    assert result["error"] == "Sandbox execution failed."
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


import threading
import time


def test_execution_capacity_is_limited_to_two():
    from app.sandbox import code_runner

    semaphore = code_runner._execution_slots

    acquired = []
    release_event = threading.Event()

    def worker():
        if semaphore.acquire(blocking=False):
            acquired.append(True)
            release_event.wait(timeout=5)
            semaphore.release()

    threads = [
        threading.Thread(target=worker)
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()

    try:
        deadline = time.monotonic() + 2

        while len(acquired) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert len(acquired) == 2
        assert semaphore.acquire(blocking=False) is False

    finally:
        release_event.set()

        for thread in threads:
            thread.join(timeout=6)

    assert semaphore.acquire(blocking=False) is True
    semaphore.release()


def test_docker_execution_uses_security_restrictions():
    from unittest.mock import MagicMock

    client = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"SECURITY_OK"

    result = CodeRunner(client=client).run_python(
        "print('SECURITY_OK')"
    )

    assert result["success"] is True

    kwargs = client.containers.run.call_args.kwargs

    assert kwargs["network_disabled"] is True
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == [
        "no-new-privileges:true",
        "seccomp=builtin",
    ]
    assert kwargs.get("privileged", False) is False
    assert kwargs["mem_limit"] == "128m"
    assert kwargs["pids_limit"] == 32
    assert kwargs["user"] == "10001:10001"
    ulimits = kwargs["ulimits"]
    assert len(ulimits) == 1
    assert ulimits[0].name == "nofile"
    assert ulimits[0].soft == 64
    assert ulimits[0].hard == 64


def test_execution_semaphore_rejects_excess_concurrency(monkeypatch):
    import threading

    from app.sandbox import code_runner as runner_module

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(
        runner_module,
        "_execution_slots",
        slots,
    )

    client = MagicMock()
    container = client.containers.run.return_value

    started = threading.Event()
    release = threading.Event()

    def blocking_wait(timeout=None):
        started.set()
        assert release.wait(timeout=5)
        return {"StatusCode": 0}

    container.wait.side_effect = blocking_wait
    container.logs.return_value = b"CONCURRENCY_OK"

    runner = CodeRunner(client=client)
    first_result = {}

    def first_execution():
        first_result["result"] = runner.run_python(
            "print('first')"
        )

    worker = threading.Thread(target=first_execution)
    worker.start()

    try:
        assert started.wait(timeout=3)

        second_result = runner.run_python(
            "print('second')"
        )

        assert second_result["success"] is False
        assert "capacity reached" in second_result["error"].lower()

        assert client.containers.run.call_count == 1

    finally:
        release.set()
        worker.join(timeout=8)

    assert not worker.is_alive()
    assert first_result["result"]["success"] is True

    # A released slot must be available again.
    assert slots.acquire(blocking=False)
    slots.release()


from unittest.mock import Mock, patch

from app.sandbox.code_runner import (
    CodeRunner,
    PYTHON_IMAGE,
)


@patch("app.sandbox.code_runner._execution_slots")
def test_container_uses_security_limits(mock_slots):
    mock_slots.acquire.return_value = True

    container = Mock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"OK"

    client = Mock()
    client.containers.run.return_value = container

    runner = CodeRunner(client=client)
    result = runner.run_python("print('OK')")

    assert result["success"] is True

    kwargs = client.containers.run.call_args.kwargs

    assert kwargs["image"] == PYTHON_IMAGE
    assert kwargs["network_disabled"] is True
    assert kwargs["mem_limit"] == "128m"
    assert kwargs["memswap_limit"] == "128m"
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["pids_limit"] == 32
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["user"] == "10001:10001"
    assert "/tmp" in kwargs["tmpfs"]

    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


@patch("app.sandbox.code_runner._execution_slots")
def test_container_does_not_receive_host_network_or_privileged_access(
    mock_slots,
):
    mock_slots.acquire.return_value = True

    container = Mock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"OK"

    client = Mock()
    client.containers.run.return_value = container

    CodeRunner(client=client).run_python("print('OK')")

    kwargs = client.containers.run.call_args.kwargs

    assert kwargs.get("privileged", False) is False
    assert "network_mode" not in kwargs
    assert "ports" not in kwargs
    assert "volumes" not in kwargs
    assert "devices" not in kwargs
