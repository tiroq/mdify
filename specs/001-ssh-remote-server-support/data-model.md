# Data Model: SSH Remote Server Support

**Status**: Phase 1 - Design  
**Last Updated**: 2026-02-03

---

## Overview

This document defines the core data structures for SSH remote server support in mdify. These models represent SSH configuration, active transfer sessions, and remote container state.

---

## SSHConfig

**Purpose**: Encapsulate SSH connection parameters from all precedence sources (CLI, ~/.mdify/remote.conf, ~/.ssh/config).

**Location**: `mdify/ssh/models.py`

### Definition

```python
@dataclass
class SSHConfig:
    """SSH connection configuration."""
    
    # Required fields
    host: str                          # Hostname or IP (from --remote-host or config)
    port: int = 22                     # SSH port (from --remote-port or config)
    username: str = ""                 # SSH username (from --remote-user or config or $USER)
    
    # Authentication
    password: str | None = None        # Password (from --remote-pass or None for key-based)
    key_file: str | None = None        # Private key path (from --remote-key or ~/.ssh/id_rsa)
    key_passphrase: str | None = None  # Key passphrase (from --remote-pass-phrase or None)
    
    # Connection behavior
    timeout: int = 30                  # Connection timeout in seconds (from config or default)
    keepalive: int = 60                # Keepalive interval in seconds (from config or default)
    compression: bool = False           # Enable SSH compression (from config or default)
    
    # Remote environment
    work_dir: str = "/tmp/mdify"       # Working directory on remote (from config or default)
    container_runtime: str | None = None  # Force runtime: 'docker' or 'podman' (from config or auto-detect)
    
    # Metadata
    source: str = "cli"                # Precedence source: 'cli', 'remote_conf', or 'ssh_config'
    config_file: str | None = None     # Source file path if loaded from config
    created_at: datetime = field(default_factory=datetime.now)  # Instantiation timestamp
    
    # Validation metadata
    validated: bool = False            # Whether resource checks have passed on remote
    validation_errors: list[str] = field(default_factory=list)  # Resource validation errors if any
```

### Class Methods

#### `from_cli_args(args: argparse.Namespace) -> SSHConfig`

**Purpose**: Create SSHConfig from CLI argument namespace.

**Parameters**:
- `args`: Parsed CLI arguments containing `--remote-host`, `--remote-user`, `--remote-port`, `--remote-key`, etc.

**Returns**: `SSHConfig` instance with source='cli'

**Validation**: 
- `host` is required
- `port` must be 1-65535
- `key_file` must exist if provided
- `timeout` and `keepalive` must be positive integers

**Example**:
```python
config = SSHConfig.from_cli_args(args)  # args.remote_host = "server.local"
# → SSHConfig(host="server.local", port=22, source="cli")
```

---

#### `from_ssh_config(host: str, ssh_config_path: str = "~/.ssh/config") -> SSHConfig`

**Purpose**: Load SSH connection parameters from OpenSSH config file.

**Parameters**:
- `host`: Host alias or hostname to look up in SSH config
- `ssh_config_path`: Path to SSH config file (defaults to ~/.ssh/config)

**Returns**: `SSHConfig` instance with source='ssh_config'

**Parsing Rules**:
- Expand `~` and `~user` to absolute paths
- Parse Include directives recursively (max 10 levels)
- Match Host and Match directives with wildcards (* and ?)
- Load: HostName, Port, User, IdentityFile, ConnectTimeout, ServerAliveInterval, Compression
- Apply first matching value for each parameter

**Special Cases**:
- If HostName not specified, use provided `host` parameter
- If User not specified, use current user ($USER)
- Multiple IdentityFile directives: return first one (others ignored)
- Handle escaped characters in values (space, comma, quote)

**Example**:
```python
config = SSHConfig.from_ssh_config("myserver")
# Parses ~/.ssh/config looking for Host myserver
# Returns SSHConfig(host="myserver.local", user="dev", key_file="~/.ssh/myserver_key")
```

---

#### `from_remote_conf(remote_conf_path: str = "~/.mdify/remote.conf") -> SSHConfig`

**Purpose**: Load SSH parameters from mdify remote config file.

**Parameters**:
- `remote_conf_path`: Path to remote config file (defaults to ~/.mdify/remote.conf)

**Returns**: `SSHConfig` instance with source='remote_conf'

**File Format**: YAML

```yaml
# ~/.mdify/remote.conf
remote_servers:
  production:
    host: prod.server.com
    port: 2222
    username: deploy
    key_file: ~/.ssh/prod_key
    timeout: 60
    container_runtime: docker
    
  staging:
    host: staging.server.com
    username: dev
    work_dir: /var/local/mdify
    container_runtime: podman
```

**Validation**:
- File must be readable YAML
- `host` is required in config
- Port, timeout must be integers if present
- Paths (key_file, work_dir) can contain ~ and environment variables

**Example**:
```python
config = SSHConfig.from_remote_conf("~/.mdify/remote.conf")
# Returns first server or raises ConfigError if file doesn't exist
```

---

#### `merge(higher_precedence: SSHConfig) -> SSHConfig`

**Purpose**: Merge two SSHConfig objects, with higher precedence values overriding defaults.

**Parameters**:
- `higher_precedence`: Config with higher precedence (e.g., CLI args override SSH config)

**Returns**: Merged SSHConfig instance

**Rule**: Non-None and non-default values from `higher_precedence` override values in `self`

**Example**:
```python
cli_config = SSHConfig.from_cli_args(args)  # host="myserver", username=None
ssh_config = SSHConfig.from_ssh_config("myserver")  # username="deploy"
merged = ssh_config.merge(cli_config)  
# → SSHConfig(host="myserver", username="deploy")  # CLI host wins, SSH config username wins
```

---

### Instance Methods

#### `validate_remote_resources() -> bool`

**Purpose**: Connect to remote server and validate available resources (disk space, memory, container runtime).

**Returns**: `True` if all checks pass, `False` if any check fails

**Side Effects**: 
- Sets `validated = True`
- Populates `validation_errors` with any failures
- Raises `SSHConnectionError` if connection fails

**Checks**:
1. SSH connection successful
2. Working directory exists or can be created
3. Container runtime available (docker or podman)
4. Minimum 5GB disk space in work_dir
5. Minimum 2GB available memory

**Example**:
```python
config = SSHConfig.from_cli_args(args)
try:
    config.validate_remote_resources()
except SSHConnectionError as e:
    print(f"Connection failed: {e}")
```

---

#### `to_dict() -> dict`

**Purpose**: Convert to dictionary for serialization or logging.

**Returns**: Dictionary with all fields (passwords and key passphrases excluded)

---

## TransferSession

**Purpose**: Track an active file transfer with progress updates, timing, and metadata.

**Location**: `mdify/ssh/transfer.py`

### Definition

```python
@dataclass
class TransferSession:
    """Active file transfer session with progress tracking."""
    
    # Identification
    session_id: str                    # UUID for session correlation
    local_path: str                    # Source file path (local or remote depending on direction)
    remote_path: str                   # Destination path on remote server
    direction: Literal["upload", "download"]  # Transfer direction
    
    # Progress tracking
    total_bytes: int                   # Total file size in bytes
    transferred_bytes: int = 0         # Bytes transferred so far
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    
    # Status
    status: Literal["pending", "in_progress", "completed", "failed", "cancelled"] = "pending"
    error_message: str | None = None   # Error details if failed
    
    # Performance metrics
    avg_speed_mbps: float = 0.0        # Average speed in MB/s
    current_speed_mbps: float = 0.0    # Current speed in MB/s (last 5 seconds)
    eta_seconds: int | None = None     # Estimated time remaining
    
    # Debugging
    debug_mode: bool = False           # Log chunk-by-chunk progress if True
    chunk_log: list[str] = field(default_factory=list)  # Debug log of transfer chunks
```

### Instance Methods

#### `update_progress(transferred_bytes: int) -> None`

**Purpose**: Update transfer progress and recalculate speed/ETA.

**Parameters**:
- `transferred_bytes`: Total bytes transferred so far

**Side Effects**: Updates `transferred_bytes`, `current_speed_mbps`, `eta_seconds`

**Calculation**:
- `current_speed_mbps = (transferred_bytes - previous_bytes) / (time_delta) / 1_000_000`
- `eta_seconds = (total_bytes - transferred_bytes) / (avg_speed_mbps * 1_000_000)`

---

#### `complete() -> None`

**Purpose**: Mark transfer as completed.

**Side Effects**: Sets `end_time`, `status = "completed"`, calculates final `avg_speed_mbps`

---

#### `fail(error: Exception) -> None`

**Purpose**: Mark transfer as failed.

**Side Effects**: Sets `status = "failed"`, `error_message`, `end_time`

---

## RemoteContainerState

**Purpose**: Represent state of a container running on remote server over SSH.

**Location**: `mdify/ssh/remote_container.py`

### Definition

```python
@dataclass
class RemoteContainerState:
    """State of a container running on a remote server."""
    
    # Container identification
    container_id: str                  # Container ID from docker/podman
    container_name: str                # Container name
    host: str                          # Remote host where running
    port: int                          # Port exposed from container
    
    # Runtime state
    runtime: Literal["docker", "podman"]  # Container runtime
    is_running: bool = False           # Whether container is currently running
    health_status: Literal["healthy", "unhealthy", "unknown"] = "unknown"
    
    # Lifecycle timestamps
    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    
    # Status details
    exit_code: int | None = None       # Exit code if stopped
    error_message: str | None = None   # Error details if health check failed
    
    # Network info
    base_url: str = ""                 # URL to access container (http://host:port)
    
    # Metadata
    created_by: str = ""               # Username who started this container
    tags: dict[str, str] = field(default_factory=dict)  # Arbitrary metadata tags
```

### Instance Methods

#### `from_docker_info(docker_dict: dict) -> RemoteContainerState`

**Purpose**: Parse Docker API inspect response into RemoteContainerState.

**Example**:
```python
state = RemoteContainerState.from_docker_info(docker_response)
```

---

#### `from_podman_info(podman_dict: dict) -> RemoteContainerState`

**Purpose**: Parse Podman API inspect response into RemoteContainerState.

---

#### `is_accessible() -> bool`

**Purpose**: Check if container is reachable and healthy.

**Returns**: `True` if running and health check passes

---

## Configuration Precedence

When loading SSH config, apply this precedence order:

1. **CLI Arguments** (highest priority)  
   - `--remote-host`, `--remote-user`, `--remote-port`, `--remote-key`, etc.
   
2. **~/.mdify/remote.conf** (medium priority)  
   - YAML config in user's home directory
   
3. **~/.ssh/config** (lowest priority)  
   - OpenSSH standard config file
   
4. **Defaults** (fallback)  
   - Port: 22
   - Username: $USER (current user)
   - Timeout: 30 seconds
   - Keepalive: 60 seconds

**Implementation Example**:
```python
# Load from lowest to highest precedence, then merge
ssh_config = SSHConfig.from_ssh_config(host)  # Lowest
if Path("~/.mdify/remote.conf").exists():
    remote_config = SSHConfig.from_remote_conf()
    ssh_config = ssh_config.merge(remote_config)

cli_config = SSHConfig.from_cli_args(args)
final_config = ssh_config.merge(cli_config)  # Highest
```

---

## Type Hints & Imports

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from pathlib import Path
import uuid
```

---

## Validation Errors

All SSHConfig methods may raise these exceptions:

- **`ConfigError`**: Invalid config file or missing required field
- **`SSHConnectionError`**: Cannot connect to remote host
- **`ValidationError`**: Resource check failed (disk space, memory, etc.)
- **`PathError`**: Specified path doesn't exist or not accessible

---
