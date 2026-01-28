"""Container lifecycle management for docling-serve."""

import subprocess
import time
import uuid
from typing import Optional

from mdify.docling_client import check_health


class DoclingContainer:
    """Manages docling-serve container lifecycle.

    Provides context manager support for automatic startup and cleanup.

    Usage:
        with DoclingContainer("docker", "ghcr.io/docling-project/docling-serve-cpu:main") as container:
            # Container is running and healthy
            response = requests.post(f"{container.base_url}/v1/convert/file", ...)
        # Container automatically stopped and removed
    """

    def __init__(self, runtime: str, image: str, port: int = 5001, timeout: int = 1200):
        """Initialize container manager.

        Args:
            runtime: Container runtime ("docker" or "podman")
            image: Container image to use
            port: Host port to bind (default: 5001)
            timeout: Conversion timeout in seconds (default: 1200)
        """
        self.runtime = runtime
        self.image = image
        self.port = port
        self.timeout = timeout
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
            "--rm",  # Auto-remove on stop
            "--name",
            self.container_name,
            "-p",
            f"{self.port}:5001",
            "-e",
            f"DOCLING_SERVE_MAX_SYNC_WAIT={self.timeout}",
            self.image,
        ]

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
