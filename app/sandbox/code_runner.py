
import logging
import threading

import docker
from docker.errors import DockerException, NotFound
from requests.exceptions import (
    ReadTimeout,
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
)

MAX_CODE_LENGTH = 8_000
MAX_OUTPUT_BYTES = 16_384
EXECUTION_TIMEOUT_SECONDS = 10
MAX_CONCURRENT_EXECUTIONS = 2

_execution_slots = threading.BoundedSemaphore(
    MAX_CONCURRENT_EXECUTIONS
)

logger = logging.getLogger(__name__)

PYTHON_IMAGE = (
    "python:3.12-alpine@sha256:"
    "5789aa194f757888f41fa3d48e14b6feaa1b57c0af0b56fcb1372d6474d3bff0"
)


def _contains_timeout(exc):
    """Detect timeout exceptions wrapped by transport errors."""
    seen = set()
    current = exc

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(
            current,
            (ReadTimeout, RequestsTimeout, TimeoutError),
        ):
            return True

        current = current.__cause__ or current.__context__

    return False


class CodeRunner:
    """Run bounded Python code in an isolated Docker container."""

    def __init__(self, client=None):
        self.client = client or docker.from_env()

    def run_python(self, code: str) -> dict:
        if not isinstance(code, str) or not code.strip():
            return {
                "success": False,
                "error": "Python code must not be empty.",
            }

        if len(code.encode("utf-8")) > MAX_CODE_LENGTH:
            return {
                "success": False,
                "error": "Python code exceeds the size limit.",
            }

        if not _execution_slots.acquire(blocking=False):
            return {
                "success": False,
                "error": "Sandbox capacity reached. Try again later.",
            }

        container = None

        try:
            container = self.client.containers.run(
                image=PYTHON_IMAGE,
                command=["python", "-I", "-c", code],
                detach=True,
                network_disabled=True,
                mem_limit="128m",
                memswap_limit="128m",
                nano_cpus=500_000_000,
                pids_limit=32,
                ulimits=[
                    docker.types.Ulimit(
                        name="nofile",
                        soft=64,
                        hard=64,
                    ),
                ],
                read_only=True,
                cap_drop=["ALL"],
                security_opt=[
                    "no-new-privileges:true",
                    "seccomp=builtin",
                ],
                user="10001:10001",
                tmpfs={
                    "/tmp": "rw,noexec,nosuid,size=8m"
                },
                working_dir="/tmp",
                labels={
                    "app": "proofrun",
                    "purpose": "code-execution",
                },
            )

            result = container.wait(
                timeout=EXECUTION_TIMEOUT_SECONDS
            )

            exit_code = result.get("StatusCode", -1)

            output = container.logs(
                stdout=True,
                stderr=True,
            )

            if not isinstance(output, bytes):
                output = b"".join(output)

            truncated = len(output) > MAX_OUTPUT_BYTES

            output = output[:MAX_OUTPUT_BYTES].decode(
                "utf-8",
                errors="replace",
            )

            return {
                "success": exit_code == 0 and not truncated,
                "exit_code": exit_code,
                "output": output,
                "output_truncated": truncated,
            }

        except (ReadTimeout, RequestsTimeout, TimeoutError):
            logger.warning(
                "Sandbox execution timed out.",
                exc_info=True,
            )
            return {
                "success": False,
                "error": "Sandbox execution timed out.",
            }

        except RequestsConnectionError as exc:
            if _contains_timeout(exc):
                logger.warning(
                    "Docker transport timed out.",
                    exc_info=True,
                )
                return {
                    "success": False,
                    "error": "Sandbox execution timed out.",
                }

            logger.error(
                "Docker transport connection failed.",
                exc_info=True,
            )
            return {
                "success": False,
                "error": "Docker connection failed.",
            }

        except DockerException:
            logger.warning(
                "Docker code execution failed.",
                exc_info=True,
            )
            return {
                "success": False,
                "error": "Sandbox execution failed.",
            }

        except Exception:
            logger.exception(
                "Unexpected sandbox execution failure."
            )
            return {
                "success": False,
                "error": "Sandbox execution failed.",
            }

        finally:
            try:
                if container is not None:
                    self._stop_container(container)
            finally:
                _execution_slots.release()

    @staticmethod
    def _stop_container(container):
        """Attempt termination and forced removal independently."""

        try:
            container.kill()
        except NotFound:
            pass
        except Exception:
            logger.warning(
                "Sandbox container kill failed; "
                "attempting forced removal.",
                exc_info=True,
            )

        try:
            container.remove(force=True)
        except NotFound:
            pass
        except Exception:
            logger.critical(
                "Sandbox container cleanup failed.",
                exc_info=True,
            )
