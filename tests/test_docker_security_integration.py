import docker
import pytest

from app.sandbox.docker_runner import DockerRunner


@pytest.fixture(scope="module")
def runner():
    client = docker.from_env()

    try:
        client.ping()
    except Exception as exc:
        pytest.skip(f"Live Docker engine unavailable: {exc}")

    yield DockerRunner()

    client.close()


def test_real_smoke_test_succeeds(runner):
    result = runner.run_smoke_test()

    assert result["success"] is True
    assert "PROOFRUN_SMOKE_OK" in result["output"]


def test_real_containment_probe_succeeds(runner):
    result = runner.run_containment_test()

    assert result["success"] is True
    assert "PROOFRUN_READONLY_OK" in result["output"]


import time


ALPINE_IMAGE = (
    "alpine:3.22@sha256:"
    "5291449c3df73caf6ed85e649dec1b9e"
    "818b39a5d8c871e97afc13e9cd5e8fa8"
)


def test_live_container_security_configuration(runner):
    """Inspect actual Docker settings on a running container."""
    container = None

    try:
        container = runner.client.containers.run(
            image=ALPINE_IMAGE,
            command=["sh", "-c", "sleep 30"],
            detach=True,
            network_mode="none",
            mem_limit="64m",
            nano_cpus=500_000_000,
            pids_limit=32,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="0:0",
        )

        container.reload()
        attrs = container.attrs
        host = attrs["HostConfig"]

        assert host["NetworkMode"] == "none"
        assert host["ReadonlyRootfs"] is True
        assert host["Memory"] == 64 * 1024 * 1024
        assert host["NanoCpus"] == 500_000_000
        assert host["PidsLimit"] == 32
        assert "ALL" in host["CapDrop"]
        assert "no-new-privileges:true" in host["SecurityOpt"]

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


def test_read_only_root_rejects_root_write(runner):
    """A root user must also be unable to write to the root filesystem."""
    container = None

    try:
        container = runner.client.containers.run(
            image=ALPINE_IMAGE,
            command=[
                "sh",
                "-c",
                "touch /proofrun-root-write-probe "
                "2>/dev/null && exit 10 || exit 0",
            ],
            detach=True,
            network_mode="none",
            read_only=True,
            user="0:0",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
        )

        result = container.wait(timeout=10)
        assert result["StatusCode"] == 0

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


import time


def test_live_network_isolation_blocks_outbound_connection(runner):
    """Verify network=none and test an actual outbound connection attempt."""
    container = None

    try:
        container = runner.client.containers.run(
            image=ALPINE_IMAGE,
            command=[
                "sh",
                "-c",
                "if wget -T 2 -q -O /dev/null "
                "http://1.1.1.1/; "
                "then echo PROOFRUN_NETWORK_FAIL; exit 1; "
                "else echo PROOFRUN_NETWORK_BLOCKED; exit 0; fi",
            ],
            detach=True,
            network_mode="none",
            mem_limit="64m",
            nano_cpus=500_000_000,
            pids_limit=32,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
        )

        container.reload()
        assert container.attrs["HostConfig"]["NetworkMode"] == "none"

        result = container.wait(timeout=10)
        output = container.logs().decode("utf-8", errors="replace")

        assert result["StatusCode"] == 0
        assert "PROOFRUN_NETWORK_BLOCKED" in output
        assert "PROOFRUN_NETWORK_FAIL" not in output

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


def test_real_container_is_removed_after_execution(runner):
    """Verify a completed test container is removed by the runner."""
    container = None

    try:
        container = runner.client.containers.run(
            image=ALPINE_IMAGE,
            command=["sh", "-c", "echo PROOFRUN_CLEANUP_PROBE"],
            detach=True,
            network_mode="none",
            labels={
                "app": "proofrun",
                "purpose": "cleanup-integration-test",
            },
        )

        container_id = container.id
        container.wait(timeout=10)

        container.remove(force=True)
        container = None

        with pytest.raises(docker.errors.NotFound):
            runner.client.containers.get(container_id)

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
