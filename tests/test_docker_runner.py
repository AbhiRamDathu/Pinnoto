from app.sandbox.docker_runner import DockerRunner

from unittest.mock import MagicMock, patch

from requests.exceptions import ReadTimeout

from app.sandbox.docker_runner import DockerRunner
from docker.errors import DockerException


def test_docker_engine_is_available():
    runner = DockerRunner()
    result = runner.health_check()

    assert result["available"] is True, result
    assert result["engine_version"]


def test_hello_world_runs_in_restricted_container():
    runner = DockerRunner()
    result = runner.run_smoke_test()

    assert result["success"] is True, result
    assert "PROOFRUN_SMOKE_OK" in result["output"]
    assert result["exit_code"] == 0


def test_timeout_returns_failure_and_removes_container():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")

    with patch("app.sandbox.docker_runner.docker.from_env"):
        result = runner.run_smoke_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"
    container.remove.assert_called_once_with(force=True)


def test_smoke_test_requests_restricted_docker_configuration():
    from unittest.mock import MagicMock, patch

    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"PROOFRUN_SMOKE_OK\n"

    with patch("app.sandbox.docker_runner.docker.from_env"):
        result = runner.run_smoke_test()

    assert result["success"] is True

    kwargs = runner.client.containers.run.call_args.kwargs
    assert kwargs["network_mode"] == "none"
    assert kwargs["mem_limit"] == "64m"
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["pids_limit"] == 32
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["user"] == "10001:10001"

    container.remove.assert_called_once_with(force=True)


def test_cleanup_error_does_not_override_timeout_failure():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")
    container.remove.side_effect = RuntimeError("simulated cleanup failure")

    result = runner.run_smoke_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"


def test_log_failure_still_removes_container():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = DockerException("simulated log failure")

    result = runner.run_smoke_test()

    assert result["success"] is False
    container.remove.assert_called_once_with(force=True)

def test_containment_test_requests_restricted_configuration():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"PROOFRUN_READONLY_OK\n"

    result = runner.run_containment_test()

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "PROOFRUN_READONLY_OK" in result["output"]

    kwargs = runner.client.containers.run.call_args.kwargs
    assert kwargs["read_only"] is True
    assert kwargs["network_mode"] == "none"
    assert kwargs["mem_limit"] == "64m"
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["pids_limit"] == 32
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["user"] == "10001:10001"

    container.remove.assert_called_once_with(force=True)


def test_containment_test_rejects_writable_root_filesystem_result():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.return_value = {"StatusCode": 1}
    container.logs.return_value = b"PROOFRUN_READONLY_FAIL\n"

    result = runner.run_containment_test()

    assert result["success"] is False
    assert result["exit_code"] == 1
    assert "PROOFRUN_READONLY_FAIL" in result["output"]
    container.remove.assert_called_once_with(force=True)


def test_containment_test_timeout_removes_container():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")

    result = runner.run_containment_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"
    container.remove.assert_called_once_with(force=True)

def test_timeout_stops_container_before_removing_it():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")

    events = []
    container.stop.side_effect = lambda timeout: events.append(
        ("stop", timeout)
    )
    container.remove.side_effect = lambda force: events.append(
        ("remove", force)
    )

    result = runner.run_smoke_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"
    assert events[0] == ("stop", 3)
    assert events[1] == ("remove", True)


def test_timeout_still_removes_container_when_stop_fails():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")
    container.stop.side_effect = RuntimeError("simulated stop failure")

    result = runner.run_smoke_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"
    container.stop.assert_called_once_with(timeout=3)
    container.remove.assert_called_once_with(force=True)

def test_unexpected_wait_error_still_removes_container():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = DockerException(
        "simulated wait failure"
    )

    result = runner.run_smoke_test()

    assert result["success"] is False
    container.remove.assert_called_once_with(force=True)


def test_timeout_preserves_failure_when_stop_and_remove_fail():
    runner = DockerRunner.__new__(DockerRunner)
    runner.client = MagicMock()

    container = MagicMock()
    runner.client.containers.run.return_value = container
    container.wait.side_effect = ReadTimeout("timed out")
    container.stop.side_effect = RuntimeError(
        "simulated stop failure"
    )
    container.remove.side_effect = RuntimeError(
        "simulated removal failure"
    )

    result = runner.run_smoke_test()

    assert result["success"] is False
    assert result["error"] == "Sandbox execution timed out"
    container.stop.assert_called_once_with(timeout=3)
    container.remove.assert_called_once_with(force=True)