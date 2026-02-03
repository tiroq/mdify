"""AsyncSSH client implementation for mdify."""

import asyncio
import logging
from typing import AsyncGenerator
from pathlib import Path
import asyncssh

from mdify.ssh.models import SSHConfig, SSHConnectionError, SSHAuthError

logger = logging.getLogger(__name__)


class AsyncSSHClient:
    """SSH client using asyncssh library."""
    
    def __init__(self, config: SSHConfig):
        """Initialize SSH client with configuration.
        
        Parameters:
            config: SSHConfig instance with connection parameters
        """
        self.config = config
        self.connection: asyncssh.SSHClientConnection | None = None
        self._retries = 0
        self._max_retries = 3
    
    async def connect(self) -> None:
        """Establish SSH connection to remote host.
        
        Uses exponential backoff for retries: 1s, 2s, 4s
        
        Raises:
            SSHConnectionError: Connection failed
            SSHAuthError: Authentication failed
        """
        backoff_delays = [1, 2, 4]
        last_error = None
        
        for attempt in range(self._max_retries):
            try:
                logger.debug(f"SSH: Connecting to {self.config.host}:{self.config.port} (attempt {attempt + 1}/{self._max_retries})")
                
                # Prepare connection parameters - only include non-None values
                connect_kwargs = {
                    "port": self.config.port,
                    "connect_timeout": self.config.timeout,
                    "known_hosts": None,  # Skip host key verification for now
                }
                
                # Add username if provided
                if self.config.username:
                    connect_kwargs["username"] = self.config.username
                
                # Add passphrase if provided
                if self.config.key_passphrase:
                    connect_kwargs["passphrase"] = self.config.key_passphrase
                
                # Use key-based authentication if provided
                if self.config.key_file:
                    key_path = Path(self.config.key_file).expanduser()
                    if not key_path.exists():
                        raise SSHConnectionError(
                            f"SSH key not found: {key_path}",
                            self.config.host,
                            self.config.port
                        )
                    connect_kwargs["client_keys"] = [str(key_path)]
                
                # Use password if provided (backup authentication)
                if self.config.password:
                    connect_kwargs["password"] = self.config.password
                
                # Establish connection
                self.connection = await asyncssh.connect(
                    self.config.host,
                    **connect_kwargs
                )
                
                logger.info(f"SSH: Connected to {self.config.host}:{self.config.port}")
                self._retries = 0
                return
                
            except asyncssh.PermissionDenied as e:
                logger.debug(f"SSH: Authentication failed: {e}")
                raise SSHAuthError(
                    f"SSH authentication failed: {e}",
                    self.config.host,
                    self.config.port
                )
            except asyncssh.misc.DisconnectError as e:
                last_error = e
                logger.debug(f"SSH: Connection error (attempt {attempt + 1}): {e}")
                
                if attempt < self._max_retries - 1:
                    delay = backoff_delays[attempt]
                    logger.debug(f"SSH: Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                logger.debug(f"SSH: Connection failed: {e}")
                raise SSHConnectionError(
                    f"SSH connection failed: {e}",
                    self.config.host,
                    self.config.port
                )
        
        # All retries exhausted
        raise SSHConnectionError(
            f"SSH connection failed after {self._max_retries} retries: {last_error}",
            self.config.host,
            self.config.port
        )
    
    async def disconnect(self) -> None:
        """Close SSH connection gracefully."""
        if self.connection:
            self.connection.close()
            await self.connection.wait_closed()
            self.connection = None
            logger.info(f"SSH: Disconnected from {self.config.host}")
    
    async def is_connected(self) -> bool:
        """Check if SSH connection is active.
        
        Returns:
            True if connected and authenticated, False otherwise
        """
        if not self.connection:
            return False
        
        try:
            # Try a simple no-op to verify connection
            await self.run_command("echo OK", timeout=5)
            return True
        except Exception:
            return False
    
    async def run_command(
        self,
        command: str,
        timeout: int | None = None
    ) -> tuple[str, str, int]:
        """Execute a command on remote server.
        
        Parameters:
            command: Shell command to execute
            timeout: Command timeout in seconds (None = no timeout)
            
        Returns:
            Tuple of (stdout, stderr, exit_code)
            
        Raises:
            SSHConnectionError: Connection lost during execution
            TimeoutError: Command exceeded timeout
        """
        if not self.connection:
            raise SSHConnectionError(
                "Not connected to remote server",
                self.config.host,
                self.config.port
            )
        
        try:
            timeout_val = timeout or self.config.timeout
            
            result = await asyncio.wait_for(
                self.connection.run(command, check=False),
                timeout=timeout_val
            )
            
            return (
                result.stdout if result.stdout else "",
                result.stderr if result.stderr else "",
                result.exit_status if result.exit_status is not None else 0
            )
            
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command timeout after {timeout} seconds: {command}")
        except Exception as e:
            raise SSHConnectionError(
                f"Command execution failed: {e}",
                self.config.host,
                self.config.port
            )
    
    async def run_command_stream(self, command: str) -> AsyncGenerator[str, None]:
        """Execute command with streaming output.
        
        Parameters:
            command: Shell command to execute
            
        Yields:
            Output lines from command as they arrive
            
        Raises:
            SSHConnectionError: Connection lost
        """
        if not self.connection:
            raise SSHConnectionError(
                "Not connected to remote server",
                self.config.host,
                self.config.port
            )
        
        try:
            async with self.connection.create_process(command) as process:
                # Read stdout line by line
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    yield line.decode('utf-8', errors='replace').rstrip('\n')
                
        except Exception as e:
            raise SSHConnectionError(
                f"Stream command failed: {e}",
                self.config.host,
                self.config.port
            )
    
    async def check_container_runtime(self) -> str | None:
        """Detect available container runtime on remote.
        
        Returns:
            "docker" if docker available
            "podman" if podman available (and docker not)
            None if neither available
        """
        if not self.config.container_runtime:
            # Auto-detect
            # Try docker first
            try:
                stdout, stderr, code = await self.run_command("which docker")
                if code == 0:
                    stdout, stderr, code = await self.run_command("docker --version")
                    if code == 0:
                        logger.info(f"SSH: Detected Docker: {stdout.strip()}")
                        return "docker"
            except Exception as e:
                logger.debug(f"SSH: Docker check failed: {e}")
            
            # Try podman
            try:
                stdout, stderr, code = await self.run_command("which podman")
                if code == 0:
                    stdout, stderr, code = await self.run_command("podman --version")
                    if code == 0:
                        logger.info(f"SSH: Detected Podman: {stdout.strip()}")
                        return "podman"
            except Exception as e:
                logger.debug(f"SSH: Podman check failed: {e}")
            
            return None
        
        # Verify configured runtime
        runtime = self.config.container_runtime.lower()
        try:
            stdout, stderr, code = await self.run_command(f"which {runtime}")
            if code == 0:
                return runtime
        except Exception as e:
            logger.debug(f"SSH: Runtime check failed: {e}")
        
        return None
    
    async def get_available_memory(self) -> int:
        """Get available memory on remote in bytes.
        
        Returns:
            Available memory in bytes
            
        Raises:
            SSHConnectionError: Connection lost
        """
        try:
            # Check if Linux
            stdout, stderr, code = await self.run_command("uname")
            if code == 0 and "Linux" in stdout:
                # Parse /proc/meminfo
                stdout, stderr, code = await self.run_command(
                    "grep MemAvailable /proc/meminfo | awk '{print $2}'"
                )
                if code == 0:
                    try:
                        kb = int(stdout.strip())
                        return kb * 1024  # Convert KB to bytes
                    except ValueError:
                        pass
            
            # Try macOS vm_stat
            stdout, stderr, code = await self.run_command("vm_stat")
            if code == 0:
                # Parse "Pages free" line
                for line in stdout.split('\n'):
                    if "Pages free" in line:
                        try:
                            pages = int(line.split()[-1].rstrip('.'))
                            page_size = 4096  # macOS page size
                            return pages * page_size
                        except (ValueError, IndexError):
                            pass
            
            # Fallback: return 2GB
            logger.warning("SSH: Could not determine available memory, assuming 2GB")
            return 2 * 1024 * 1024 * 1024
            
        except Exception as e:
            logger.warning(f"SSH: Memory check failed: {e}")
            return 2 * 1024 * 1024 * 1024
    
    async def get_available_disk(self, path: str) -> int:
        """Get available disk space for path on remote.
        
        Parameters:
            path: Filesystem path to check
            
        Returns:
            Available space in bytes
            
        Raises:
            SSHConnectionError: Connection lost
        """
        try:
            # Expand path
            expanded_path = path.replace("~", "$HOME")
            
            # Run df -B1 (block size 1 byte for accurate output)
            stdout, stderr, code = await self.run_command(
                f"df -B1 {expanded_path} | tail -1 | awk '{{print $4}}'"
            )
            
            if code == 0:
                try:
                    return int(stdout.strip())
                except ValueError:
                    pass
            
            # Fallback: return 10GB
            logger.warning("SSH: Could not determine disk space, assuming 10GB")
            return 10 * 1024 * 1024 * 1024
            
        except Exception as e:
            logger.warning(f"SSH: Disk check failed: {e}")
            return 10 * 1024 * 1024 * 1024
    
    async def validate_remote_resources(self) -> dict[str, bool]:
        """Run comprehensive resource validation checks.
        
        Returns:
            Dict with validation results
        """
        results = {
            "can_connect": False,
            "work_dir_exists": False,
            "work_dir_writable": False,
            "container_runtime_available": False,
            "disk_space_min_5gb": False,
            "memory_min_2gb": False,
            "ssh_config_valid": False,
        }
        
        try:
            # Test connection
            if await self.is_connected():
                results["can_connect"] = True
                results["ssh_config_valid"] = True
            else:
                return results
            
            # Check work directory
            work_dir = self.config.work_dir
            stdout, stderr, code = await self.run_command(f"test -d {work_dir}")
            if code == 0:
                results["work_dir_exists"] = True
            else:
                # Try to create it
                stdout, stderr, code = await self.run_command(f"mkdir -p {work_dir}")
                if code == 0:
                    results["work_dir_exists"] = True
            
            # Check write access
            if results["work_dir_exists"]:
                stdout, stderr, code = await self.run_command(
                    f"touch {work_dir}/.mdify_test_$$"
                )
                if code == 0:
                    results["work_dir_writable"] = True
                    # Clean up
                    await self.run_command(f"rm {work_dir}/.mdify_test_$$")
            
            # Check container runtime
            runtime = await self.check_container_runtime()
            results["container_runtime_available"] = runtime is not None
            
            # Check disk space
            available_disk = await self.get_available_disk(work_dir)
            results["disk_space_min_5gb"] = available_disk >= (5 * 1024 * 1024 * 1024)
            
            # Check memory
            available_mem = await self.get_available_memory()
            results["memory_min_2gb"] = available_mem >= (2 * 1024 * 1024 * 1024)
            
            return results
            
        except Exception as e:
            logger.error(f"SSH: Resource validation error: {e}")
            return results
