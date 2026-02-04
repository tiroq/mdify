"""Data models for SSH remote server support."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from pathlib import Path
import uuid


class SSHError(Exception):
    """Base exception for SSH operations."""


class SSHConnectionError(SSHError):
    """Connection establishment or maintenance failed."""
    def __init__(self, message: str, host: str, port: int):
        self.message = message
        self.host = host
        self.port = port
        super().__init__(f"{message} ({host}:{port})")


class SSHAuthError(SSHConnectionError):
    """Authentication failed (bad password, key, or permissions)."""


class ConfigError(SSHError):
    """Configuration is invalid or incomplete."""


class ValidationError(SSHError):
    """Resource validation check failed."""


@dataclass
class SSHConfig:
    """SSH connection configuration with precedence-aware merging."""
    
    # Required fields
    host: str
    port: int = 22
    username: str = ""
    
    # Authentication
    password: str | None = None
    key_file: str | None = None
    key_passphrase: str | None = None
    
    # Connection behavior
    timeout: int = 30
    keepalive: int = 60
    compression: bool = False
    
    # Remote environment
    work_dir: str = "/tmp/mdify"
    container_runtime: str | None = None
    
    # Metadata
    source: str = "cli"
    config_file: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Validation metadata
    validated: bool = False
    validation_errors: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate config after initialization."""
        if not self.host:
            raise ConfigError("host is required")
        if not 1 <= self.port <= 65535:
            raise ConfigError(f"port must be 1-65535, got {self.port}")
        if self.timeout < 1:
            raise ConfigError(f"timeout must be positive, got {self.timeout}")
    
    @classmethod
    def from_cli_args(cls, args) -> "SSHConfig":
        """Create SSHConfig from CLI argument namespace.
        
        Parameters:
            args: Parsed CLI arguments (argparse.Namespace)
            
        Returns:
            SSHConfig instance with source='cli'
            
        Raises:
            ConfigError: Invalid configuration
        """
        # Extract only CLI-provided values (not defaults)
        kwargs = {"source": "cli"}
        
        if hasattr(args, "remote_host") and args.remote_host:
            kwargs["host"] = args.remote_host
        if hasattr(args, "remote_port") and args.remote_port:
            kwargs["port"] = args.remote_port
        if hasattr(args, "remote_user") and args.remote_user:
            kwargs["username"] = args.remote_user
        if hasattr(args, "remote_key") and args.remote_key:
            kwargs["key_file"] = args.remote_key
        if hasattr(args, "remote_key_pass_phrase") and args.remote_key_pass_phrase:
            kwargs["key_passphrase"] = args.remote_key_pass_phrase
        if hasattr(args, "remote_timeout") and args.remote_timeout:
            kwargs["timeout"] = args.remote_timeout
        if hasattr(args, "remote_keepalive") and args.remote_keepalive:
            kwargs["keepalive"] = args.remote_keepalive
        if hasattr(args, "remote_work_dir") and args.remote_work_dir:
            kwargs["work_dir"] = args.remote_work_dir
        if hasattr(args, "remote_runtime") and args.remote_runtime:
            kwargs["container_runtime"] = args.remote_runtime
        if hasattr(args, "remote_compression") and args.remote_compression:
            kwargs["compression"] = args.remote_compression
        
        # For partial configs (CLI may only override one or two fields),
        # we need a default host to create the object
        if "host" not in kwargs:
            kwargs["host"] = "localhost"  # Temporary, will be overridden by merge
        
        return cls(**kwargs)
    
    @classmethod
    def from_ssh_config(cls, host: str, ssh_config_path: str | None = None) -> "SSHConfig":
        """Load SSH config for host from ~/.ssh/config.
        
        Parameters:
            host: Host alias or hostname to look up
            ssh_config_path: Path to SSH config file (defaults to ~/.ssh/config)
            
        Returns:
            SSHConfig instance with source='ssh_config'
            
        Raises:
            ConfigError: SSH config file not found or invalid
        """
        import os
        from pathlib import Path
        
        if ssh_config_path is None:
            ssh_config_path = "~/.ssh/config"
        
        ssh_config_path = os.path.expanduser(ssh_config_path)
        
        if not Path(ssh_config_path).exists():
            # SSH config is optional; return defaults if not found
            return cls(
                host=host,
                source="ssh_config",
                config_file=ssh_config_path,
            )
        
        try:
            # For SSH config loading, we'll use a simple approach:
            # Parse the SSH config file ourselves to extract host configuration
            config_data = cls._parse_ssh_config_file(ssh_config_path, host)
            
            kwargs = {
                "source": "ssh_config",
                "config_file": ssh_config_path,
                "host": config_data.get("hostname", host),
            }
            
            if "port" in config_data:
                kwargs["port"] = int(config_data["port"])
            if "user" in config_data:
                kwargs["username"] = config_data["user"]
            if "identityfile" in config_data:
                # Use first identity file, expand ~ if present
                identity_files = config_data["identityfile"]
                if isinstance(identity_files, list):
                    kwargs["key_file"] = os.path.expanduser(identity_files[0])
                else:
                    kwargs["key_file"] = os.path.expanduser(identity_files)
            if "connecttimeout" in config_data:
                kwargs["timeout"] = int(config_data["connecttimeout"])
            if "serveraliveinterval" in config_data:
                kwargs["keepalive"] = int(config_data["serveraliveinterval"])
            if "compression" in config_data:
                compression_str = config_data["compression"]
                kwargs["compression"] = compression_str.lower() in ("yes", "true", "1")
            
            return cls(**kwargs)
            
        except Exception as e:
            raise ConfigError(f"Failed to load SSH config: {e}")
    
    @staticmethod
    def _parse_ssh_config_file(config_path: str, target_host: str) -> dict:
        """Parse SSH config file for a specific host.
        
        Parameters:
            config_path: Path to SSH config file
            target_host: Host alias to look for
            
        Returns:
            Dictionary of configuration values for the host
        """
        config_data = {}
        current_hosts = []
        in_target_block = False
        
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Check for Host directive
                    if line.lower().startswith('host '):
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            hosts = parts[1].split()
                            in_target_block = target_host in hosts or '*' in hosts
                            if not in_target_block:
                                config_data = {}
                        continue
                    
                    # Parse config directives
                    if in_target_block:
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            key = parts[0].lower()
                            value = parts[1]
                            
                            # Handle multi-value options (identity files)
                            if key == 'identityfile':
                                if key not in config_data:
                                    config_data[key] = []
                                if isinstance(config_data[key], list):
                                    config_data[key].append(value)
                                else:
                                    config_data[key] = [config_data[key], value]
                            else:
                                # For single-value options, use the first occurrence
                                if key not in config_data:
                                    config_data[key] = value
        except Exception as e:
            raise ConfigError(f"Failed to parse SSH config file {config_path}: {e}")
        
        return config_data

    
    @classmethod
    def from_remote_conf(cls, remote_conf_path: str | None = None) -> "SSHConfig":
        """Load SSH config from ~/.mdify/remote.conf.
        
        Parameters:
            remote_conf_path: Path to remote config file
            
        Returns:
            SSHConfig instance with source='remote_conf'
            
        Raises:
            ConfigError: Config file not found or invalid
        """
        import yaml
        import os
        
        if remote_conf_path is None:
            remote_conf_path = "~/.mdify/remote.conf"
        
        remote_conf_path = os.path.expanduser(remote_conf_path)
        
        if not Path(remote_conf_path).exists():
            raise ConfigError(f"Remote config file not found: {remote_conf_path}")
        
        try:
            with open(remote_conf_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
            
            # Extract defaults
            defaults = config_data.get("defaults", {})
            servers = config_data.get("servers", {})
            
            if not servers:
                raise ConfigError("No servers defined in remote config")
            
            # Use first server or named one
            first_server_name = next(iter(servers.keys()))
            server_config = servers[first_server_name]
            
            # Merge defaults with server config (server overrides defaults)
            merged = {**defaults, **server_config}
            
            # Build SSHConfig
            kwargs = {
                "source": "remote_conf",
                "config_file": remote_conf_path,
            }
            
            if "host" in merged:
                kwargs["host"] = merged["host"]
            else:
                raise ConfigError(f"Server '{first_server_name}' missing 'host' field")
            
            if "port" in merged:
                kwargs["port"] = int(merged["port"])
            if "username" in merged:
                kwargs["username"] = merged["username"]
            if "key_file" in merged:
                kwargs["key_file"] = merged["key_file"]
            if "timeout" in merged:
                kwargs["timeout"] = int(merged["timeout"])
            if "keepalive" in merged:
                kwargs["keepalive"] = int(merged["keepalive"])
            if "compression" in merged:
                kwargs["compression"] = bool(merged["compression"])
            if "work_dir" in merged:
                kwargs["work_dir"] = merged["work_dir"]
            if "container_runtime" in merged:
                kwargs["container_runtime"] = merged["container_runtime"]
            
            return cls(**kwargs)
            
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in remote config: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load remote config: {e}")
    
    def merge(self, higher_precedence: "SSHConfig") -> "SSHConfig":
        """Merge with higher precedence config.
        
        Parameters:
            higher_precedence: Config with higher precedence (e.g., CLI args)
            
        Returns:
            Merged SSHConfig with higher precedence values
        """
        # Use higher precedence value if provided, otherwise use self
        def pick_value(self_val, higher_val, is_string=True):
            if is_string:
                return higher_val if higher_val else self_val
            else:
                return higher_val if higher_val is not None else self_val
        
        return SSHConfig(
            host=pick_value(self.host, higher_precedence.host),
            port=pick_value(self.port, higher_precedence.port, is_string=False),
            username=pick_value(self.username, higher_precedence.username),
            password=pick_value(self.password, higher_precedence.password),
            key_file=pick_value(self.key_file, higher_precedence.key_file),
            key_passphrase=pick_value(self.key_passphrase, higher_precedence.key_passphrase),
            timeout=pick_value(self.timeout, higher_precedence.timeout, is_string=False),
            keepalive=pick_value(self.keepalive, higher_precedence.keepalive, is_string=False),
            compression=pick_value(self.compression, higher_precedence.compression, is_string=False),
            work_dir=pick_value(self.work_dir, higher_precedence.work_dir),
            container_runtime=pick_value(self.container_runtime, higher_precedence.container_runtime),
            source=higher_precedence.source,  # Track higher precedence source
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization (excludes secrets)."""
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username or "default",
            "timeout": self.timeout,
            "keepalive": self.keepalive,
            "compression": self.compression,
            "work_dir": self.work_dir,
            "container_runtime": self.container_runtime or "auto-detect",
            "source": self.source,
        }


@dataclass
class TransferSession:
    """Active file transfer session with progress tracking."""
    
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    local_path: str = ""
    remote_path: str = ""
    direction: Literal["upload", "download"] = "upload"
    
    # Progress tracking
    total_bytes: int = 0
    transferred_bytes: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    
    # Status
    status: Literal["pending", "in_progress", "completed", "failed", "cancelled"] = "pending"
    error_message: str | None = None
    
    # Performance metrics
    avg_speed_mbps: float = 0.0
    current_speed_mbps: float = 0.0
    eta_seconds: int | None = None
    
    # Debugging
    debug_mode: bool = False
    chunk_log: list[str] = field(default_factory=list)
    
    def update_progress(self, transferred_bytes: int) -> None:
        """Update transfer progress and recalculate speed/ETA."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        if elapsed <= 0:
            return
        
        self.transferred_bytes = transferred_bytes
        self.avg_speed_mbps = (transferred_bytes / elapsed) / (1024 * 1024)
        
        if self.avg_speed_mbps > 0 and self.transferred_bytes < self.total_bytes:
            remaining_bytes = self.total_bytes - self.transferred_bytes
            self.eta_seconds = int(remaining_bytes / (self.avg_speed_mbps * 1024 * 1024))
        else:
            self.eta_seconds = None
    
    def complete(self) -> None:
        """Mark transfer as completed."""
        self.end_time = datetime.now()
        self.status = "completed"
        
        elapsed = (self.end_time - self.start_time).total_seconds()
        if elapsed > 0:
            self.avg_speed_mbps = (self.total_bytes / elapsed) / (1024 * 1024)
    
    def fail(self, error: Exception) -> None:
        """Mark transfer as failed."""
        self.end_time = datetime.now()
        self.status = "failed"
        self.error_message = str(error)


@dataclass
class RemoteContainerState:
    """State of a container running on a remote server."""
    
    container_id: str = ""
    container_name: str = ""
    host: str = ""
    port: int = 8000
    
    # Runtime state
    runtime: Literal["docker", "podman"] = "docker"
    is_running: bool = False
    health_status: Literal["healthy", "unhealthy", "unknown"] = "unknown"
    
    # Lifecycle timestamps
    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    
    # Status details
    exit_code: int | None = None
    error_message: str | None = None
    
    # Network info
    base_url: str = ""
    
    # Metadata
    created_by: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    
    def is_accessible(self) -> bool:
        """Check if container is running and healthy."""
        return self.is_running and self.health_status == "healthy"
