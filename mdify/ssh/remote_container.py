"""Remote container management over SSH."""

import logging
import uuid
from typing import Literal
from mdify.container import DoclingContainer
from mdify.ssh.models import RemoteContainerState, SSHConnectionError

logger = logging.getLogger(__name__)


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
        self.ssh_client = ssh_client
        self.image = image
        self.port = port
        self.runtime = runtime
        self.name = name or f"mdify-{uuid.uuid4().hex[:8]}"
        self.timeout = timeout
        self.health_check_interval = health_check_interval
        
        self.state = RemoteContainerState(
            container_name=self.name,
            port=port,
            runtime=runtime,
            host=ssh_client.config.host,
            base_url=f"http://{ssh_client.config.host}:{port}"
        )
        self.is_healthy = False
    
    async def start(self) -> None:
        """Start container on remote server.
        
        Operations:
        1. Detect container runtime on remote
        2. Run docker/podman run command
        3. Extract container ID
        4. Wait for health check
        
        Raises:
            RuntimeError: Container already running or start failed
            SSHConnectionError: SSH connection lost
        """
        if self.state.is_running:
            raise RuntimeError(f"Container {self.name} is already running")
        
        logger.info(f"Starting remote container: {self.name}")
        
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
            
            stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=self.timeout)
            
            if code != 0:
                logger.warning(f"Container stop returned code {code}: {stderr}")
            
            # Remove container
            cmd = f"{self.runtime} rm {self.state.container_id}"
            stdout, stderr, code = await self.ssh_client.run_command(cmd, timeout=self.timeout)
            
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
