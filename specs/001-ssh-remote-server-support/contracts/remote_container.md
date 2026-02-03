# Contract: RemoteContainer Interface

**Status**: Phase 1 - Design  
**Version**: 1.0  
**Last Updated**: 2026-02-03

---

## Overview

The `RemoteContainer` interface extends the base `Container` abstraction to add SSH-based remote container management capabilities. This enables starting, stopping, and managing containers on a remote server.

**Location**: `mdify/ssh/remote_container.py`

**Base Class**: Inherits from `mdify.container.Container`

---

## Interface Definition

```python
class RemoteContainer(Container):
    """Container running on remote server via SSH."""
    
    def __init__(
        self,
        ssh_client: SSHClient,
        image: str,
        port: int,
        runtime: Literal["docker", "podman"] = "docker",
        name: str | None = None,
        timeout: int = 30,
        health_check_interval: int = 2
    ) -> None:
        """Initialize remote container manager.
        
        Parameters:
            ssh_client: Connected SSHClient instance
            image: Container image name (e.g., "docling-serve:latest")
            port: Port to expose from container
            runtime: Container runtime ("docker" or "podman")
            name: Container name (defaults to auto-generated)
            timeout: Timeout for health checks in seconds
            health_check_interval: Poll interval for health checks in seconds
        """
        
    @property
    async def state(self) -> RemoteContainerState:
        """Get current container state.
        
        Returns:
            RemoteContainerState with current status, health, and metadata
            
        Raises:
            SSHConnectionError: Connection lost
        """
```

---

## Lifecycle Contract

```python
@abstractmethod
async def start(self) -> None:
    """Start container on remote server.
    
    Operations:
        1. Run `docker/podman run ...` command
        2. Extract container ID from output
        3. Poll health endpoint with exponential backoff
        4. Wait for container to be healthy or timeout
        
    Raises:
        RuntimeError: Container already running
        SSHConnectionError: Connection lost
        TimeoutError: Container didn't become healthy within timeout
    """

@abstractmethod
async def stop(self, force: bool = False) -> None:
    """Stop container on remote server.
    
    Parameters:
        force: If True, kill container; if False, graceful stop
        
    Operations:
        1. Run `docker/podman stop|kill` command
        2. Wait for container to exit
        3. Remove container
        
    Raises:
        RuntimeError: Container not running
        SSHConnectionError: Connection lost
    """

@abstractmethod
async def is_running(self) -> bool:
    """Check if container is running.
    
    Returns:
        True if container exists and is in 'running' state
        
    Implementation:
        - Run `docker/podman ps` and grep for container_id
        
    Raises:
        SSHConnectionError: Connection lost
    """

@abstractmethod
async def check_health(self) -> bool:
    """Check container health via HTTP GET to base_url.
    
    Returns:
        True if health endpoint returns 200 OK
        False if connection refused, timeout, or non-200 response
        
    Raises:
        SSHConnectionError: Connection lost (not RuntimeError)
    """

@abstractmethod
async def get_logs(self, lines: int = 50) -> str:
    """Get container logs from remote.
    
    Parameters:
        lines: Number of recent log lines to retrieve
        
    Returns:
        Container logs as string
        
    Implementation:
        - Run `docker/podman logs --tail {lines}` command
        - Return stdout
        
    Raises:
        SSHConnectionError: Connection lost
    """
```

---

## Remote-Specific Methods

```python
@abstractmethod
async def push_image(self, image: str, registry: str | None = None) -> None:
    """Push container image to remote server before running.
    
    Parameters:
        image: Full image name with tag
        registry: Optional registry URL (e.g., docker.io)
        
    Operations:
        1. Check if image already exists on remote (docker image inspect)
        2. If not, pull image from registry
        3. Verify image is available locally before starting
        
    Raises:
        SSHConnectionError: Connection lost
        ImageNotFoundError: Image unavailable in registry
    """

@abstractmethod
async def get_port_mapping(self) -> int:
    """Get actual port mapping for exposed container port.
    
    Returns:
        Actual port number on remote host
        
    Implementation:
        - Run `docker/podman port container_name`
        - Parse output to extract host port
        
    Notes:
        - Useful if port is specified as 0 (random port allocation)
        
    Raises:
        SSHConnectionError: Connection lost
        RuntimeError: Container not running
    """

@abstractmethod
async def get_resource_usage(self) -> dict[str, Any]:
    """Get real-time resource usage of container.
    
    Returns:
        Dict with resource metrics:
        {
            "cpu_percent": float,           # CPU usage 0-100%
            "memory_bytes": int,            # Memory used in bytes
            "memory_percent": float,        # Memory % of limit
            "network_in_bytes": int,        # Network input
            "network_out_bytes": int,       # Network output
            "block_read_bytes": int,        # Disk read
            "block_write_bytes": int,       # Disk write
        }
        
    Implementation:
        - Run `docker/podman stats --no-stream` command
        - Parse and format output
        
    Raises:
        SSHConnectionError: Connection lost
        RuntimeError: Container not running
    """
```

---

## Error Recovery

```python
@abstractmethod
async def reconnect(self) -> None:
    """Reconnect SSH session if lost.
    
    Operations:
        1. Verify SSH connection is still valid
        2. If lost, reconnect using SSHConfig
        3. Re-validate container state on remote
        
    Raises:
        SSHConnectionError: Reconnection failed
    """

@abstractmethod
async def handle_connection_loss(self) -> None:
    """Handle SSH connection loss gracefully.
    
    Operations:
        1. Mark container state as 'unknown'
        2. Attempt automatic reconnection (3 retries)
        3. Re-query container state if reconnected
        4. If reconnection fails, raise SSHConnectionError
        
    Raises:
        SSHConnectionError: Reconnection and re-validation failed
    """
```

---

## State Synchronization

```python
@abstractmethod
async def refresh_state(self) -> None:
    """Force refresh of container state from remote.
    
    Operations:
        1. Run `docker/podman inspect container_id`
        2. Update internal state object
        3. Validate container is still accessible
        
    Raises:
        SSHConnectionError: Connection lost
        ContainerNotFoundError: Container no longer exists on remote
    """
```

---

## Container Creation Command

The `start()` method generates a docker/podman command like:

```bash
# Docker example
docker run \
  --name mdify-docling-<UUID> \
  --publish 8000:8000 \
  --detach \
  --health-cmd='curl -f http://localhost:8000/health || exit 1' \
  --health-interval=2s \
  --health-timeout=5s \
  --health-retries=3 \
  docling-serve:latest

# Podman equivalent
podman run \
  --name mdify-docling-<UUID> \
  --publish 8000:8000 \
  --detach \
  --health-cmd='curl -f http://localhost:8000/health || exit 1' \
  --health-interval=2s \
  --health-timeout=5s \
  --health-retries=3 \
  docling-serve:latest
```

---

## Error Handling

```python
class RemoteContainerError(Exception):
    """Base exception for remote container operations."""

class ContainerNotFoundError(RemoteContainerError):
    """Container doesn't exist on remote."""
    def __init__(self, container_id: str, host: str):
        self.container_id = container_id
        self.host = host

class ImageNotFoundError(RemoteContainerError):
    """Container image not available."""
    def __init__(self, image: str, registry: str):
        self.image = image
        self.registry = registry

class ContainerHealthError(RemoteContainerError):
    """Container failed health check."""
    def __init__(self, container_id: str, attempts: int):
        self.container_id = container_id
        self.attempts = attempts
```

---

## Implementation Notes

1. **State Caching**: Cache container state locally with 2-second TTL to avoid excessive remote calls
2. **Health Checks**: Use HTTP GET with 5-second timeout, retry up to 3 times with 2-second intervals
3. **Port Mapping**: Store port mapping after container creation to avoid repeated queries
4. **Graceful Shutdown**: Always attempt `stop` before `kill` to allow container cleanup
5. **Log Rotation**: Limit log retrieval to 50 lines to avoid large data transfers

---

## Testing Requirements

- Unit tests for all state transitions (stopped → running → healthy)
- Mock SSHClient for isolated testing
- Integration tests with real container on local SSH server
- Connection loss and reconnection scenarios
- Timeout and health check failure handling
- Resource usage calculation verification

---
