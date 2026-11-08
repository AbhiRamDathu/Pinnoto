import docker
import pytest

IMAGE = (
    "alpine:3.22@sha256:"
    "5291449c3df73caf6ed85e649dec1b9e"
    "818b39a5d8c871e97afc13e9cd5e8fa8"
)


@pytest.fixture
def client():
    c = docker.from_env()
    try:
        c.ping()
    except Exception as exc:
        c.close()
        pytest.skip(f"Docker unavailable: {exc}")
    yield c
    c.close()


def test_live_resource_limits_are_enforced_in_configuration(client):
    container = None
    try:
        container = client.containers.run(
            IMAGE,
            command=["sh", "-c", "sleep 5"],
            detach=True,
            network_mode="none",
            mem_limit="64m",
            memswap_limit="64m",
            nano_cpus=500_000_000,
            pids_limit=16,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
            labels={"app": "proofrun", "purpose": "resource-test"},
        )

        container.reload()
        attrs = container.attrs
        host = attrs["HostConfig"]

        assert host["Memory"] == 64 * 1024 * 1024
        assert host["MemorySwap"] == 64 * 1024 * 1024
        assert host["NanoCpus"] == 500_000_000
        assert host["PidsLimit"] == 16
        assert host["ReadonlyRootfs"] is True
        assert host["NetworkMode"] == "none"
        assert host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]

    finally:
        if container is not None:
            try:
                container.kill()
            except docker.errors.DockerException:
                pass
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass


def test_memory_exhaustion_is_contained(client):
    container = None
    try:
        container = client.containers.run(
            "python:3.12-alpine",
            command=[
                "python",
                "-c",
                "x = bytearray(256 * 1024 * 1024); print('UNEXPECTED_SUCCESS')",
            ],
            detach=True,
            network_mode="none",
            mem_limit="64m",
            memswap_limit="64m",
            nano_cpus=500_000_000,
            pids_limit=16,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
            labels={"app": "proofrun", "purpose": "resource-test"},
        )

        result = container.wait(timeout=20)
        container.reload()

        state = container.attrs["State"]
        output = container.logs(
            stdout=True, stderr=True
        ).decode("utf-8", errors="replace")

        assert (
            result["StatusCode"] != 0 or state.get("OOMKilled") is True
        ), f"Memory exhaustion unexpectedly succeeded: {output}"

        assert "UNEXPECTED_SUCCESS" not in output

    finally:
        if container is not None:
            try:
                container.kill()
            except docker.errors.DockerException:
                pass
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
