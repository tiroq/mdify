"""Remote container management over SSH."""

import logging
import uuid
from typing import Literal, List, Tuple
from mdify.container import (
    DoclingContainer,
    CleanupSummary,
    CleanupFailure,
    MANAGED_CONTAINER_PREFIXES,
)
from mdify.ssh.models import RemoteContainerState

logger = logging.getLogger(__name__)


async def _list_managed_containers(
    ssh_client,
    runtime: str,
    prefixes: Tuple[str, ...] = MANAGED_CONTAINER_PREFIXES,
) -> List[Tuple[str, str]]:
    """List managed containers on remote with their state."""
    cmd = f"{runtime} ps -a --format '{{{{.Names}}}}\t{{{{.State}}}}'"
    stdout, stderr, code = await ssh_client.run_command(cmd, timeout=10)
    if code != 0 or not stdout.strip():
        return []

    managed: List[Tuple[str, str]] = []
    for line in stdout.strip().split("\n"):
        parts = line.strip().split("\t", 1)
        name = parts[0].strip() if parts else ""
        state = parts[1].strip().lower() if len(parts) > 1 else "unknown"
        if name and any(name.startswith(prefix) for prefix in prefixes):
            managed.append((name, state))
    return managed


async def cleanup_managed_containers(
    ssh_client,
    runtime: str,
    prefixes: Tuple[str, ...] = MANAGED_CONTAINER_PREFIXES,
    retry_once: bool = True,
) -> CleanupSummary:
    """Stop and remove managed containers on remote with a single retry."""
    summary = CleanupSummary(target="remote", runtime=runtime)

    async def attempt_cleanup() -> Tuple[int, int, List[CleanupFailure]]:
        stopped = 0
        removed = 0
        failures: List[CleanupFailure] = []
        containers = await _list_managed_containers(ssh_client, runtime, prefixes=prefixes)
        for container_name, state in containers:
            stopped_ok = True
            if state == "running":
                stop_cmd = f"{runtime} stop {container_name}"
                _stdout, stderr, code = await ssh_client.run_command(stop_cmd, timeout=10)
                if code != 0:
                    failures.append(
                        CleanupFailure(
                            container_name=container_name,
                            action="stop",
                            reason=stderr.strip() or "Stop failed",
                            exit_code=code,
                        )
                    )
                    stopped_ok = False
                else:
                    stopped += 1

            if stopped_ok:
                rm_cmd = f"{runtime} rm {container_name}"
                _stdout, stderr, code = await ssh_client.run_command(rm_cmd, timeout=10)
                if code != 0:
                    failures.append(
                        CleanupFailure(
                            container_name=container_name,
                            action="remove",
                            reason=stderr.strip() or "Remove failed",
                            exit_code=code,
                        )
                    )
                else:
                    removed += 1

        return stopped, removed, failures

    stopped, removed, failures = await attempt_cleanup()
    summary.stopped_count += stopped
    summary.removed_count += removed
    summary.failures = failures

    if failures and retry_once:
        summary.retry_attempted = True
        stopped_retry, removed_retry, failures_retry = await attempt_cleanup()
        summary.stopped_count += stopped_retry
        summary.removed_count += removed_retry
        summary.failures = failures_retry

    return summary


class RemoteContainer(DoclingContainer):
    """Container running on remote server via SSH."""
    
    def __init__(
        self,
        ssh_client,
        image: str = "docling-serve:latest",
        port: int = 8000,
        runtime: Literal["docker", "podman"] = "docker",
        name: str | None = None,
        timeout: int = 30,
        health_check_interval: int = 2
    ):
        """Initialize remote container manager.
        
        Parameters:
            ssh_client: Connected AsyncSSHClient instance
            image: Container image name
            port: Port to expose from container
            runtime: Container runtime ("docker" or "podman")
            name: Container name (auto-generated if None)
            timeout: Timeout for operations in seconds
            health_check_interval: Health check poll interval in seconds
        """
        # Initialize base class
        super().__init__(
            runtime=runtime,
            image=image,
            port=port,
            timeout=timeout
        )
        
        self.ssh_client = ssh_client
        self.name = name or f"mdify-{uuid.uuid4().hex[:8]}"
        self.health_check_interval = health_check_interval
        
        self.state = RemoteContainerState(
            container_name=self.name,
            port=port,
            runtime=runtime,
            host=ssh_client.config.host,
            base_url=f"http://{ssh_client.config.host}:{port}"
        )
        self.is_healthy = False
    
    async def _cleanup_port(self) -> None:
        """Clean up any existing containers using this port.
        
        Attempts to find and stop containers that are bound to self.port.
        This handles the case where a previous container wasn't properly cleaned up.
        """
        try:
            # Find containers using this port
            # Using docker inspect with port filter
            cmd = f"{self.runtime} ps -a --filter 'publish={int(self.port)}' --format '{{{{.ID}}}}'"
            stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=10)
            
            if code == 0 and stdout.strip():
                container_ids = stdout.strip().split('\n')
                for container_id in container_ids:
                    container_id = container_id.strip()
                    if not container_id:
                        continue
                    
                    logger.info(f"Cleaning up existing container on port {self.port}: {container_id}")
                    
                    # Stop the container
                    stop_cmd = f"{self.runtime} stop {container_id}"
                    await self.ssh_client.run_command(stop_cmd, timeout=10)
                    
                    # Remove the container
                    rm_cmd = f"{self.runtime} rm {container_id}"
                    await self.ssh_client.run_command(rm_cmd, timeout=10)
                    
                    logger.debug(f"Container removed: {container_id}")
        except Exception as e:
            logger.debug(f"Port cleanup check failed (non-blocking): {e}")

    async def start(self) -> None:
        """Start container on remote server.
        
        Operations:
        1. Clean up any existing containers using this port
        2. Detect container runtime on remote
        3. Run docker/podman run command
        4. Extract container ID
        5. Wait for health check
        
        Raises:
            RuntimeError: Container already running or start failed
            SSHConnectionError: SSH connection lost
        """
        if self.state.is_running:
            raise RuntimeError(f"Container {self.name} is already running")
        
        logger.info(f"Starting remote container: {self.name}")
        
        # Clean up any existing containers on this port
        await self._cleanup_port()
        
        try:
            # Detect runtime if needed
            if not self.runtime:
                runtime = await self.ssh_client.check_container_runtime()
                if not runtime:
                    raise RuntimeError("No container runtime available on remote")
                self.runtime = runtime
            
            # Build docker/podman command
            cmd = (
                f"{self.runtime} run "
                f"--name {self.name} "
                f"--publish {self.port}:5001 "
                f"--env DOCLING_SERVE_MAX_SYNC_WAIT={self.timeout} "
                f"--detach "
                f"{self.image}"
            )
            
            logger.debug(f"Running: {cmd}")
            stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=self.timeout)
            
            if code != 0:
                raise RuntimeError(f"Container start failed: {stderr}")
            
            # Extract container ID
            container_id = stdout.strip()
            self.state.container_id = container_id
            self.state.is_running = True
            
            logger.info(f"Container started: {container_id}")
            
            # Wait for health check
            await self._wait_for_health()
            
        except Exception as e:
            self.state.is_running = False
            logger.error(f"Container start failed: {e}")
            raise
    
    async def stop(self, force: bool = False) -> None:
        """Stop container on remote server.
        
        Parameters:
            force: If True, kill container; if False, graceful stop
            
        Raises:
            RuntimeError: Container not running
            SSHConnectionError: SSH connection lost
        """
        if not self.state.is_running:
            raise RuntimeError(f"Container {self.name} is not running")
        
        logger.info(f"Stopping remote container: {self.name}")
        
        try:
            action = "stop" if not force else "kill"
            cmd = f"{self.runtime} {action} {self.state.container_id}"
            
            _stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=self.timeout)
            
            if code != 0:
                logger.warning(f"Container stop returned code {code}: {stderr}")
            
            # Remove container
            cmd = f"{self.runtime} rm {self.state.container_id}"
            _stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=self.timeout)
            
            if code != 0:
                logger.warning(f"Container remove returned code {code}: {stderr}")
            else:
                logger.debug(f"Container removed: {self.state.container_id}")
            
            self.state.is_running = False
            logger.info(f"Container stopped: {self.state.container_id}")
            
        except Exception as e:
            logger.error(f"Container stop failed: {e}")
            raise
    
    async def is_running(self) -> bool:
        """Check if container is running.
        
        Returns:
            True if container is running
        """
        try:
            cmd = f"{self.runtime} ps --filter name={self.state.container_id} --format '{{{{.ID}}}}'"
            stdout, stderr, code = await self.ssh_client.run_command(cmd)
            
            is_running = code == 0 and stdout.strip() != ""
            self.state.is_running = is_running
            return is_running
            
        except Exception as e:
            logger.error(f"Could not check if running: {e}")
            return False
    
    async def check_health(self) -> bool:
        """Check container health.
        
        Returns:
            True if health check passes
        """
        if not self.state.is_running:
            return False
        
        try:
            # Use curl inside SSH session to check if service responds
            # The docling-serve doesn't have a /health endpoint, so we check if it responds at all
            cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{self.port}/"
            stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=5)
            
            # Any HTTP response (even 404) means the service is running
            http_code = stdout.strip()
            is_healthy = http_code in ["200", "404", "422"]  # 404 = Not Found is OK, 422 = Unprocessable Entity
            self.state.health_status = "healthy" if is_healthy else "unhealthy"
            return is_healthy
            
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            self.state.health_status = "unknown"
            return False
    
    async def get_logs(self, lines: int = 50) -> str:
        """Get container logs.
        
        Parameters:
            lines: Number of recent log lines
            
        Returns:
            Container logs as string
        """
        try:
            cmd = f"{self.runtime} logs --tail {lines} {self.state.container_id}"
            stdout, stderr, code = await self.ssh_client.run_command(cmd)
            
            return stdout if code == 0 else f"Error getting logs: {stderr}"
            
        except Exception as e:
            logger.error(f"Could not get logs: {e}")
            return f"Error: {e}"
    
    async def _wait_for_health(self, max_attempts: int = 30) -> None:
        """Wait for container to become healthy.
        
        Parameters:
            max_attempts: Maximum health check attempts
            
        Raises:
            TimeoutError: Container didn't become healthy
        """
        import asyncio
        
        for attempt in range(max_attempts):
            if await self.check_health():
                self.is_healthy = True
                logger.info(f"Container became healthy after {attempt * self.health_check_interval}s")
                return
            
            await asyncio.sleep(self.health_check_interval)
        
        raise TimeoutError(
            f"Container did not become healthy after {max_attempts * self.health_check_interval}s"
        )
