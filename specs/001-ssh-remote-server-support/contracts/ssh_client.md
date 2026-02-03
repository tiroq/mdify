# Contract: SSHClient Interface

**Status**: Phase 1 - Design  
**Version**: 1.0  
**Last Updated**: 2026-02-03

---

## Overview

The `SSHClient` interface defines the contract for SSH operations including connection management, remote command execution, file transfer, and resource validation.

**Location**: `mdify/ssh/client.py`

---

## Interface Definition

```python
class SSHClient(ABC):
    """Abstract SSH client interface."""
    
    def __init__(self, config: SSHConfig) -> None:
        """Initialize SSH client with configuration."""
        
    @abstractmethod
    async def connect(self) -> None:
        """Establish SSH connection to remote host.
        
        Raises:
            SSHConnectionError: Connection failed (timeout, auth failure, host unreachable)
            ConfigError: Invalid configuration
        """
        
    @abstractmethod
    async def disconnect(self) -> None:
        """Close SSH connection gracefully."""
        
    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if SSH connection is active.
        
        Returns:
            True if connected and authenticated, False otherwise.
        """
        
    @abstractmethod
    async def run_command(self, command: str, timeout: int | None = None) -> tuple[str, str, int]:
        """Execute a command on remote server.
        
        Parameters:
            command: Shell command to execute (e.g., "which docker")
            timeout: Command timeout in seconds (None = no timeout)
            
        Returns:
            Tuple of (stdout, stderr, exit_code)
            
        Raises:
            SSHConnectionError: Connection lost during execution
            TimeoutError: Command exceeded timeout
        """
        
    @abstractmethod
    async def run_command_stream(self, command: str) -> AsyncGenerator[str, None]:
        """Execute command with streaming output.
        
        Yields:
            Output lines from command as they arrive
            
        Raises:
            SSHConnectionError: Connection lost
        """
```

---

## File Transfer Contract

```python
@abstractmethod
async def upload_file(
    self,
    local_path: str,
    remote_path: str,
    progress_callback: Callable[[int], None] | None = None,
    overwrite: bool = False
) -> TransferSession:
    """Upload file to remote server via SFTP.
    
    Parameters:
        local_path: Local file path (must exist)
        remote_path: Destination path on remote (absolute or relative to work_dir)
        progress_callback: Called with transferred_bytes after each chunk
        overwrite: If True, overwrite existing file; if False, raise FileExistsError
        
    Returns:
        TransferSession with progress metadata
        
    Raises:
        FileNotFoundError: local_path doesn't exist
        FileExistsError: remote_path exists and overwrite=False
        PermissionError: No write access to remote_path
        SSHConnectionError: Connection lost during transfer
    """

@abstractmethod
async def download_file(
    self,
    remote_path: str,
    local_path: str,
    progress_callback: Callable[[int], None] | None = None,
    overwrite: bool = False
) -> TransferSession:
    """Download file from remote server via SFTP.
    
    Parameters:
        remote_path: Source file on remote (absolute or relative to work_dir)
        local_path: Destination local path (parent must be writable)
        progress_callback: Called with transferred_bytes after each chunk
        overwrite: If True, overwrite existing file; if False, raise FileExistsError
        
    Returns:
        TransferSession with progress metadata
        
    Raises:
        FileNotFoundError: remote_path doesn't exist
        FileExistsError: local_path exists and overwrite=False
        PermissionError: No write access to local_path
        SSHConnectionError: Connection lost during transfer
    """

@abstractmethod
async def get_file_size(self, remote_path: str) -> int:
    """Get remote file size in bytes.
    
    Raises:
        FileNotFoundError: remote_path doesn't exist
        PermissionError: No read access
    """
```

---

## Resource Validation Contract

```python
@abstractmethod
async def check_container_runtime(self) -> Literal["docker", "podman", None]:
    """Detect available container runtime on remote.
    
    Returns:
        "docker" if docker available and functional
        "podman" if podman available (and docker not available)
        None if neither available
        
    Implementation:
        1. Run: which docker
        2. If found, run: docker --version (to verify functional)
        3. Run: which podman
        4. If found, run: podman --version (to verify functional)
        5. Return first working runtime (docker preferred)
        
    Raises:
        SSHConnectionError: Connection lost
    """

@abstractmethod
async def get_available_memory(self) -> int:
    """Get available memory on remote in bytes.
    
    Returns:
        Available memory in bytes
        
    Implementation:
        - On Linux: Parse /proc/meminfo MemAvailable
        - On macOS: Run vm_stat and calculate from page counts
        - On Windows: (Not currently supported, raise NotImplementedError)
        
    Raises:
        SSHConnectionError: Connection lost
        NotImplementedError: OS not supported
    """

@abstractmethod
async def get_available_disk(self, path: str) -> int:
    """Get available disk space for path on remote.
    
    Parameters:
        path: Filesystem path to check (absolute or relative to work_dir)
        
    Returns:
        Available space in bytes
        
    Implementation:
        - Run: df path (Linux/macOS)
        - Parse output to extract available space
        
    Raises:
        FileNotFoundError: Path doesn't exist
        SSHConnectionError: Connection lost
    """

@abstractmethod
async def validate_remote_resources(self) -> dict[str, bool]:
    """Run comprehensive resource validation checks.
    
    Returns:
        Dict with validation results:
        {
            "can_connect": bool,
            "work_dir_exists": bool,
            "work_dir_writable": bool,
            "container_runtime_available": bool,
            "disk_space_min_5gb": bool,
            "memory_min_2gb": bool,
            "ssh_config_valid": bool,
        }
        
    Side Effects:
        - Creates work_dir if it doesn't exist (and writable)
        - Updates SSHConfig.validated and validation_errors
    """
```

---

## Error Handling

```python
class SSHError(Exception):
    """Base exception for SSH operations."""

class SSHConnectionError(SSHError):
    """Connection establishment or maintenance failed."""
    def __init__(self, message: str, host: str, port: int):
        self.message = message
        self.host = host
        self.port = port

class SSHAuthError(SSHConnectionError):
    """Authentication failed (bad password, key, or permissions)."""

class SSHCommandError(SSHError):
    """Command execution failed."""
    def __init__(self, command: str, exit_code: int, stderr: str):
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr

class ConfigError(SSHError):
    """Configuration is invalid or incomplete."""

class ValidationError(SSHError):
    """Resource validation check failed."""
```

---

## Implementation Notes

1. **Connection Pooling**: SSHClient should reuse single connection for multiple operations
2. **Reconnection**: Implement exponential backoff reconnection (3 retries, 1s → 2s → 4s)
3. **Keepalive**: Send periodic keepalive packets (interval from SSHConfig)
4. **Timeout Handling**: All operations should respect SSHConfig.timeout
5. **Progress Chunks**: SFTP progress callbacks should fire after each 64KB chunk
6. **Debug Mode**: If SSHConfig.debug_mode, log each chunk transfer: `Transferred 65536 bytes (1.2MB/s)`

---

## Testing Requirements

- Unit tests for all error conditions
- Mock asyncssh for isolated testing
- Integration tests with local SSH server
- Progress callback verification
- Timeout and reconnection scenarios
- File permissions and disk space edge cases

---
