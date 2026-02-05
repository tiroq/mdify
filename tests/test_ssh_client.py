"""Tests for SSH client implementation."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from mdify.ssh.models import SSHConfig, SSHConnectionError, ConfigError
from mdify.ssh.client import AsyncSSHClient
from mdify.ssh.remote_container import cleanup_managed_containers


class TestSSHConfig:
    """Tests for SSHConfig data class."""
    
    def test_ssh_config_init_valid(self):
        """Test creating valid SSHConfig."""
        config = SSHConfig(host="example.com", port=22, username="user")
        assert config.host == "example.com"
        assert config.port == 22
        assert config.username == "user"
    
    def test_ssh_config_init_missing_host(self):
        """Test that host is required."""
        with pytest.raises(ConfigError):
            SSHConfig(host="", port=22)
    
    def test_ssh_config_init_invalid_port(self):
        """Test that port must be in valid range."""
        with pytest.raises(ConfigError):
            SSHConfig(host="example.com", port=0)
        
        with pytest.raises(ConfigError):
            SSHConfig(host="example.com", port=70000)
    
    def test_ssh_config_from_cli_args(self):
        """Test loading config from CLI args."""
        args = Mock()
        args.remote_host = "example.com"
        args.remote_port = 2222
        args.remote_user = "deploy"
        args.remote_key = None
        args.remote_key_pass_phrase = None
        args.remote_timeout = None
        args.remote_keepalive = None
        args.remote_work_dir = None
        args.remote_runtime = None
        args.remote_compression = None
        
        config = SSHConfig.from_cli_args(args)
        assert config.host == "example.com"
        assert config.port == 2222
        assert config.username == "deploy"
        assert config.source == "cli"
    
    def test_ssh_config_merge_precedence(self):
        """Test that merge respects precedence."""
        base = SSHConfig(
            host="base.com",
            port=22,
            username="base_user",
            timeout=30
        )
        
        override = SSHConfig(
            host="override.com",
            port=2222,
            username="",  # Empty = use base
            timeout=60
        )
        
        merged = base.merge(override)
        assert merged.host == "override.com"  # Override wins
        assert merged.port == 2222
        assert merged.username == "base_user"  # Base wins (override empty)
        assert merged.timeout == 60


class TestAsyncSSHClient:
    """Tests for AsyncSSHClient."""
    
    @pytest.mark.asyncio
    async def test_client_init(self):
        """Test client initialization."""
        config = SSHConfig(host="example.com", port=22, username="user")
        client = AsyncSSHClient(config)
        
        assert client.config == config
        assert client.connection is None
        assert client._retries == 0
    
    @pytest.mark.asyncio
    async def test_is_connected_no_connection(self):
        """Test is_connected returns False when not connected."""
        config = SSHConfig(host="example.com", port=22)
        client = AsyncSSHClient(config)
        
        assert await client.is_connected() is False
    
    @pytest.mark.asyncio
    async def test_run_command_not_connected(self):
        """Test run_command raises when not connected."""
        config = SSHConfig(host="example.com", port=22)
        client = AsyncSSHClient(config)
        
        with pytest.raises(SSHConnectionError):
            await client.run_command("echo test")
    
    @pytest.mark.asyncio
    async def test_disconnect_no_connection(self):
        """Test disconnect gracefully handles no connection."""
        config = SSHConfig(host="example.com", port=22)
        client = AsyncSSHClient(config)
        
        # Should not raise
        await client.disconnect()
        assert client.connection is None


class TestRemoteResourceValidation:
    """Tests for remote resource validation."""
    
    @pytest.mark.asyncio
    @patch('asyncssh.connect')
    async def test_validate_remote_resources_not_connected(self, mock_connect):
        """Test validation when not connected."""
        config = SSHConfig(host="example.com", port=22)
        client = AsyncSSHClient(config)
        
        results = await client.validate_remote_resources()
        
        # All should be False when not connected
        assert results["can_connect"] is False
        assert results["ssh_config_valid"] is False


class TestConfigParsing:
    """Tests for configuration file parsing."""
    
    def test_config_to_dict(self):
        """Test converting config to dictionary (excludes secrets)."""
        config = SSHConfig(
            host="example.com",
            port=2222,
            username="user",
            password="secret",  # Should be excluded
            key_file="~/.ssh/key"
        )
        
        config_dict = config.to_dict()
        
        assert config_dict["host"] == "example.com"
        assert config_dict["port"] == 2222
        assert "password" not in config_dict  # Secrets excluded
        assert "key_file" not in config_dict  # Secrets excluded


class TestRemoteCleanup:
    """Tests for remote cleanup helpers."""

    @pytest.mark.asyncio
    async def test_cleanup_managed_containers_remote(self):
        """Cleanup stops running containers and removes managed containers on remote."""
        ssh_client = Mock()

        async def run_command_side_effect(cmd, timeout=None):
            if "ps -a" in cmd:
                return (
                    "mdify-remote-1\trunning\nmdify-foo\texited\n",
                    "",
                    0,
                )
            return ("", "", 0)

        ssh_client.run_command = AsyncMock(side_effect=run_command_side_effect)

        summary = await cleanup_managed_containers(ssh_client, "docker")

        assert summary.stopped_count == 1
        assert summary.removed_count == 2
        assert summary.failures == []

        calls = [call.args[0] for call in ssh_client.run_command.call_args_list]
        assert any("stop mdify-remote-1" in call for call in calls)
        assert any("rm mdify-remote-1" in call for call in calls)
        assert any("rm mdify-foo" in call for call in calls)
