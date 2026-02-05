"""Container lifecycle management for docling-serve."""

import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from mdify.docling_client import check_health


MANAGED_CONTAINER_PREFIXES: Tuple[str, ...] = (
    "mdify-serve-",
    "mdify-remote-",
    "mdify-",
)


@dataclass
class CleanupFailure:
    """Represents a container cleanup failure."""

    container_name: str
    action: str
    reason: str
    exit_code: Optional[int] = None


@dataclass
class CleanupSummary:
    """Summary of cleanup actions."""

    target: str
    runtime: str
    stopped_count: int = 0
    removed_count: int = 0
    failures: List[CleanupFailure] = field(default_factory=list)
    retry_attempted: bool = False
    proceeded_after_failure: bool = False


def _list_managed_containers(
    runtime: str,
    prefixes: Tuple[str, ...] = MANAGED_CONTAINER_PREFIXES,
) -> List[Tuple[str, str]]:
    """List managed containers with their state.

    Returns list of (name, state) tuples.
    """
    result = subprocess.run(
        [runtime, "ps", "-a", "--format", "{{.Names}}\t{{.State}}"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return []

    managed: List[Tuple[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split("\t", 1)
        name = parts[0].strip() if parts else ""
        state = parts[1].strip().lower() if len(parts) > 1 else "unknown"
        if name and any(name.startswith(prefix) for prefix in prefixes):
            managed.append((name, state))

    return managed


def cleanup_managed_containers(
    runtime: str,
    prefixes: Tuple[str, ...] = MANAGED_CONTAINER_PREFIXES,
    retry_once: bool = True,
) -> CleanupSummary:
    """Stop and remove managed containers with a single retry on failure."""
    runtime_name = os.path.basename(runtime)
    summary = CleanupSummary(target="local", runtime=runtime_name)

    def attempt_cleanup() -> Tuple[int, int, List[CleanupFailure]]:
        stopped = 0
        removed = 0
        failures: List[CleanupFailure] = []
        containers = _list_managed_containers(runtime, prefixes=prefixes)
        for container_name, state in containers:
            stopped_ok = True
            if state == "running":
                stop_result = subprocess.run(
                    [runtime, "stop", container_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if stop_result.returncode != 0:
                    failures.append(
                        CleanupFailure(
                            container_name=container_name,
                            action="stop",
                            reason=stop_result.stderr.strip()
                            or stop_result.stdout.strip()
                            or "Stop failed",
                            exit_code=stop_result.returncode,
                        )
                    )
                    stopped_ok = False
                else:
                    stopped += 1

            if stopped_ok:
                rm_result = subprocess.run(
                    [runtime, "rm", container_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if rm_result.returncode != 0:
                    failures.append(
                        CleanupFailure(
                            container_name=container_name,
                            action="remove",
                            reason=rm_result.stderr.strip()
                            or rm_result.stdout.strip()
                            or "Remove failed",
                            exit_code=rm_result.returncode,
                        )
                    )
                else:
                    removed += 1

        return stopped, removed, failures

    stopped, removed, failures = attempt_cleanup()
    summary.stopped_count += stopped
    summary.removed_count += removed
    summary.failures = failures

    if failures and retry_once:
        summary.retry_attempted = True
        stopped_retry, removed_retry, failures_retry = attempt_cleanup()
        summary.stopped_count += stopped_retry
        summary.removed_count += removed_retry
        summary.failures = failures_retry

    return summary


class DoclingContainer:
    """Manages docling-serve container lifecycle.

    Provides context manager support for automatic startup and cleanup.

    Usage:
        with DoclingContainer("docker", "ghcr.io/docling-project/docling-serve-cpu:main") as container:
            # Container is running and healthy
            response = requests.post(f"{container.base_url}/v1/convert/file", ...)
        # Container automatically stopped and removed
    """

    def __init__(
        self,
        runtime: str,
        image: str,
        port: int = 5001,
        timeout: int = 1200,
        keep_container: bool = False,
        memory: Optional[str] = None,
        cpus: Optional[int] = None,
    ):
        """Initialize container manager.

        Args:
            runtime: Container runtime ("docker" or "podman")
            image: Container image to use
            port: Host port to bind (default: 5001)
            timeout: Conversion timeout in seconds (default: 1200)
            keep_container: If True, do not auto-remove container (preserve logs)
            memory: Memory limit (e.g., "2g", "512m"). None for no limit.
            cpus: Number of CPUs to allocate. None for no limit.
        """
        self.runtime = runtime
        self.image = image
        self.port = port
        self.timeout = timeout
        self.keep_container = keep_container
        self.memory = memory
        self.cpus = cpus
        self.container_name = f"mdify-serve-{uuid.uuid4().hex[:8]}"
        self.container_id: Optional[str] = None

    @property
    def base_url(self) -> str:
        """Return base URL for API requests."""
        return f"http://localhost:{self.port}"

    def _cleanup_stale_containers(self) -> None:
        """Stop any existing mdify-serve containers.

        This handles the case where a previous run left a container running
        (e.g., due to crash, interrupt, or timeout).
        """
        # Find running containers matching mdify-serve-* pattern
        result = subprocess.run(
            [
                self.runtime,
                "ps",
                "--filter",
                "name=mdify-serve-",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return

        # Stop each stale container
        for container_name in result.stdout.strip().split("\n"):
            if container_name:
                subprocess.run(
                    [self.runtime, "stop", container_name],
                    capture_output=True,
                    check=False,
                )

    def start(self, timeout: int = 120) -> None:
        """Start container and wait for health check.

        Args:
            timeout: Maximum seconds to wait for health (default: 120)

        Raises:
            subprocess.CalledProcessError: If container fails to start
            TimeoutError: If health check doesn't pass within timeout
        """
        self._cleanup_stale_containers()

        # Start container in detached mode
        cmd = [
            self.runtime,
            "run",
            "-d",  # Detached mode
            "--name",
            self.container_name,
            "-p",
            f"{self.port}:5001",
            "-e",
            f"DOCLING_SERVE_MAX_SYNC_WAIT={self.timeout}",
            self.image,
        ]
        if not self.keep_container:
            cmd.insert(3, "--rm")  # Auto-remove on stop
        
        # Add resource limits if specified
        if self.cpus:
            cmd.insert(3, str(self.cpus))
            cmd.insert(3, "--cpus")
        
        if self.memory:
            cmd.insert(3, self.memory)
            cmd.insert(3, "-m")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.container_id = result.stdout.strip()
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() or e.stdout.strip() or "Unknown error"
            raise subprocess.CalledProcessError(
                e.returncode,
                e.cmd,
                output=e.stdout,
                stderr=f"Failed to start container: {error_msg}",
            )

        # Wait for health check
        self._wait_for_health(timeout)

    def stop(self) -> None:
        """Stop and remove container. Safe to call multiple times."""
        if self.container_name:
            subprocess.run(
                [self.runtime, "stop", self.container_name],
                capture_output=True,
                check=False,
            )

    def remove(self) -> None:
        """Remove container. Safe to call multiple times."""
        if self.container_name:
            subprocess.run(
                [self.runtime, "rm", "-f", self.container_name],
                capture_output=True,
                check=False,
            )

    def get_logs(self, tail: int = 50) -> tuple[str, str]:
        """Get container logs for debugging.

        Args:
            tail: Number of lines to retrieve from end of logs

        Returns:
            Tuple of (stdout, stderr) from container logs
        """
        if not self.container_name:
            return ("", "No container name set")
        
        try:
            import os
            runtime_name = os.path.basename(self.runtime)
            
            # Apple Container uses -n instead of --tail
            if runtime_name == "container":
                cmd = [self.runtime, "logs", "-n", str(tail), self.container_name]
            else:
                cmd = [self.runtime, "logs", "--tail", str(tail), self.container_name]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return ("", f"Failed to get logs (exit {result.returncode}): {result.stderr}")
            # Container logs come from both stdout and stderr
            combined = result.stdout + result.stderr
            return (combined, "")
        except Exception as e:
            return ("", f"Exception getting logs: {e}")

    def is_running(self) -> bool:
        """Check if container process is still running.

        Returns:
            True if container is running, False otherwise
        """
        if not self.container_name:
            return False
        
        try:
            result = subprocess.run(
                [self.runtime, "ps", "-q", "-f", f"name={self.container_name}"],
                capture_output=True,
                check=False,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def is_ready(self) -> bool:
        """Check if container is healthy.

        Returns:
            True if container is healthy, False otherwise
        """
        try:
            return check_health(self.base_url)
        except Exception:
            return False

    def _wait_for_health(self, timeout: int) -> None:
        """Poll health endpoint until ready.

        Args:
            timeout: Maximum seconds to wait

        Raises:
            TimeoutError: If health check doesn't pass within timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                if check_health(self.base_url):
                    return
            except Exception:
                pass
            time.sleep(2)  # Poll every 2 seconds

        raise TimeoutError(f"Container failed to become healthy within {timeout}s")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.stop()
        return False
