
import docker
from docker.errors import DockerException
from requests.exceptions import ReadTimeout
import logging

class DockerRunner:
    def __init__(self):
        self.client = docker.from_env()

    def health_check(self) -> dict:
        try:
            version = self.client.version()
            return {
                "available": True,
                "engine_version": version.get("Version"),
            }
        except DockerException:
            return {
                "available": False,
                "error": "Docker engine unavailable",
            }

    def run_smoke_test(self) -> dict:
        container = None
        try:
            container = self.client.containers.run(
                image="alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8",
                command=["sh", "-c", "echo PROOFRUN_SMOKE_OK"],
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

            try:
                result = container.wait(timeout=15)
            except ReadTimeout:
                try:
                    container.stop(timeout=3)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to stop timed-out Docker container"
                    )

                return {
                    "success": False,
                    "error": "Sandbox execution timed out",
                }
            exit_code = result.get("StatusCode", -1)
            logs = container.logs(stdout=True, stderr=True)
            output_text = logs.decode("utf-8", errors="replace")

            return {
                "success": exit_code == 0 and "PROOFRUN_SMOKE_OK" in output_text,
                "exit_code": exit_code,
                "output": output_text,
            }
        except DockerException as exc:
            return {
                "success": False,
                "error": str(exc),
            }
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to remove Docker smoke-test container"
                    )


    def run_containment_test(self) -> dict:
        """Verify that the container root filesystem is read-only."""
        container = None

        try:
            container = self.client.containers.run(
                image=(
                    "alpine:3.22@sha256:"
                    "5291449c3df73caf6ed85e649dec1b9e"
                    "818b39a5d8c871e97afc13e9cd5e8fa8"
                ),
                command=[
                    "sh",
                    "-c",
                    (
                        "if touch /proofrun-readonly-probe 2>/dev/null; "
                        "then echo PROOFRUN_READONLY_FAIL; exit 1; "
                        "else echo PROOFRUN_READONLY_OK; fi"
                    ),
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

            try:
                result = container.wait(timeout=15)
            except ReadTimeout:
                try:
                    container.stop(timeout=3)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to stop timed-out containment container"
                    )
                return {
                    "success": False,
                    "error": "Sandbox execution timed out",
                }

            exit_code = result.get("StatusCode", -1)
            output = container.logs(
                stdout=True, stderr=True
            ).decode("utf-8", errors="replace")

            return {
                "success": (
                    exit_code == 0
                    and "PROOFRUN_READONLY_OK" in output
                    and "PROOFRUN_READONLY_FAIL" not in output
                ),
                "exit_code": exit_code,
                "output": output,
            }

        except DockerException:
            return {
                "success": False,
                "error": "Sandbox execution failed",
            }

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to remove containment-test container"
                    )
