"""Tests for mdify CLI runtime detection."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, Mock, AsyncMock
import pytest
from urllib.error import URLError

from mdify.cli import (
    detect_runtime,
    is_daemon_running,
    parse_args,
    format_size,
    format_duration,
    _compare_versions,
    _get_remote_version,
    _should_check_for_update,
    _update_last_check_time,
    check_for_update,
    get_files_to_convert,
    get_output_path,
    check_image_exists,
    pull_image,
    get_image_size_estimate,
    _handle_cleanup_failure,
    _print_cleanup_summary,
    main_async_remote,
)
from mdify.container import CleanupSummary, CleanupFailure
from mdify.formatting import Colorizer


@pytest.fixture
def isolated_mdify_home(tmp_path, monkeypatch):
    """Redirect MDIFY_HOME and LAST_CHECK_FILE to tmp_path.

    This MUST be used for any test that could trigger _update_last_check_time(),
    which includes ALL check_for_update() tests EXCEPT when the function
    returns early due to MDIFY_NO_UPDATE_CHECK=1.
    """
    fake_home = tmp_path / ".mdify"
    fake_last_check = fake_home / ".last_check"
    monkeypatch.setattr("mdify.cli.MDIFY_HOME", fake_home)
    monkeypatch.setattr("mdify.cli.LAST_CHECK_FILE", fake_last_check)
    return fake_home, fake_last_check


class TestDetectRuntime:
    """Tests for detect_runtime() function."""

    def test_auto_docker_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/docker" if x == "docker" else None
                )
                result = detect_runtime(explicit=False)
                assert result == "/usr/bin/docker"

    def test_auto_only_podman_exists(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/podman" if x == "podman" else None
                )
                result = detect_runtime(explicit=False)
                assert result == "/usr/bin/podman"
                captured = capsys.readouterr()
                assert captured.err == ""

    def test_auto_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime(explicit=False)
            assert result is None

    def test_explicit_docker_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/docker" if x == "docker" else None
                )
                result = detect_runtime("docker", explicit=True)
                assert result == "/usr/bin/docker"

    def test_explicit_docker_fallback_to_podman(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/podman" if x == "podman" else None
                )
                result = detect_runtime("docker", explicit=True)
                assert result == "/usr/bin/podman"
                # With new macOS priority-based detection, priority order is used

    def test_explicit_docker_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime("docker", explicit=True)
            assert result is None

    def test_explicit_podman_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/podman" if x == "podman" else None
                )
                result = detect_runtime("podman", explicit=True)
                assert result == "/usr/bin/podman"

    def test_explicit_podman_fallback_to_docker(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            with patch("mdify.cli.is_daemon_running", return_value=True):
                mock_which.side_effect = (
                    lambda x: "/usr/bin/docker" if x == "docker" else None
                )
                result = detect_runtime("podman", explicit=True)
                assert result == "/usr/bin/docker"
                # With new macOS priority-based detection, priority order is used

    def test_explicit_podman_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime("podman", explicit=True)
            assert result is None

    # Tests for new macOS native tool support
    def test_env_var_override_orbstack(self, monkeypatch):
        """Test MDIFY_CONTAINER_RUNTIME env var overrides detection."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "orbstack")
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/orbstack"
            result = detect_runtime(explicit=False)
            assert result == "/usr/local/bin/orbstack"

    def test_env_var_override_colima_rejected(self, monkeypatch, capsys):
        """Test MDIFY_CONTAINER_RUNTIME=colima is rejected (colima is a VM manager, not a container CLI)."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "colima")
        with patch("mdify.cli.shutil.which", return_value=None):
            with patch("mdify.cli.platform.system", return_value="Linux"):
                result = detect_runtime(explicit=False)
                assert result is None
                captured = capsys.readouterr()
                assert "MDIFY_CONTAINER_RUNTIME='colima' is not supported" in captured.err

    def test_env_var_not_found_in_path(self, monkeypatch, capsys):
        """Test MDIFY_CONTAINER_RUNTIME env var when tool not in PATH."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "orbstack")
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime(explicit=False)
            assert result is None
            captured = capsys.readouterr()
            assert "MDIFY_CONTAINER_RUNTIME='orbstack' specified but not found in PATH" in captured.err

    def test_env_var_invalid_name(self, monkeypatch, capsys):
        """Test MDIFY_CONTAINER_RUNTIME with invalid runtime name."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "invalid")
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime(explicit=False)
            assert result is None
            captured = capsys.readouterr()
            assert "MDIFY_CONTAINER_RUNTIME='invalid' is not supported" in captured.err

    def test_macos_priority_orbstack_first(self, monkeypatch):
        """Test macOS prefers OrbStack over other tools."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")  # Clear env override
        with patch("mdify.cli.platform.system", return_value="Darwin"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running") as mock_running:
                    # Setup: orbstack exists and running
                    mock_which.side_effect = lambda x: f"/usr/local/bin/{x}" if x == "orbstack" else None
                    mock_running.return_value = True
                    result = detect_runtime(explicit=False)
                    assert result == "/usr/local/bin/orbstack"

    def test_macos_fallback_podman_when_orbstack_not_running(self, monkeypatch):
        """Test macOS falls back to Podman if OrbStack not running."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")
        with patch("mdify.cli.platform.system", return_value="Darwin"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running") as mock_running:
                    # Setup: orbstack exists but not running, podman exists and running
                    def which_side_effect(x):
                        if x in ("orbstack", "podman"):
                            return f"/usr/local/bin/{x}"
                        return None
                    
                    def running_side_effect(path):
                        return "podman" in path
                    
                    mock_which.side_effect = which_side_effect
                    mock_running.side_effect = running_side_effect
                    result = detect_runtime(explicit=False)
                    assert result == "/usr/local/bin/podman"

    def test_non_macos_priority_docker_first(self, monkeypatch):
        """Test non-macOS prefers Docker over other tools."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")
        with patch("mdify.cli.platform.system", return_value="Linux"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running") as mock_running:
                    # Setup: docker and podman exist, docker running
                    def which_side_effect(x):
                        if x in ("docker", "podman"):
                            return f"/usr/bin/{x}"
                        return None
                    
                    def running_side_effect(path):
                        return "docker" in path
                    
                    mock_which.side_effect = which_side_effect
                    mock_running.side_effect = running_side_effect
                    result = detect_runtime(explicit=False)
                    assert result == "/usr/bin/docker"

    def test_macos_priority_apple_container_first(self, monkeypatch):
        """Test macOS prefers Apple Container over other tools."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")
        with patch("mdify.cli.platform.system", return_value="Darwin"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running") as mock_running:
                    # Setup: container exists and running
                    mock_which.side_effect = lambda x: f"/usr/local/bin/{x}" if x == "container" else None
                    mock_running.return_value = True
                    result = detect_runtime(explicit=False)
                    assert result == "/usr/local/bin/container"

    def test_macos_fallback_orbstack_when_container_not_running(self, monkeypatch):
        """Test macOS falls back to OrbStack if Apple Container not running."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")
        with patch("mdify.cli.platform.system", return_value="Darwin"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running") as mock_running:
                    # Setup: container exists but not running, orbstack exists and running
                    def which_side_effect(x):
                        if x in ("container", "orbstack"):
                            return f"/usr/local/bin/{x}"
                        return None
                    
                    def running_side_effect(path):
                        return "orbstack" in path
                    
                    mock_which.side_effect = which_side_effect
                    mock_running.side_effect = running_side_effect
                    result = detect_runtime(explicit=False)
                    assert result == "/usr/local/bin/orbstack"

    def test_all_tools_exist_but_not_running(self, monkeypatch, capsys):
        """Test warning when tools exist but none are running."""
        monkeypatch.setenv("MDIFY_CONTAINER_RUNTIME", "")
        with patch("mdify.cli.platform.system", return_value="Darwin"):
            with patch("mdify.cli.shutil.which") as mock_which:
                with patch("mdify.cli.is_daemon_running", return_value=False):
                    def which_side_effect(x):
                        if x in ("orbstack", "podman", "docker"):
                            return f"/usr/local/bin/{x}"
                        return None
                    
                    mock_which.side_effect = which_side_effect
                    result = detect_runtime(explicit=False)
                    assert result is None
                    captured = capsys.readouterr()
                    assert "daemon is not running" in captured.err
                    assert "orbstack" in captured.err
                    assert "docker" in captured.err


class TestNewCLIArgs:
    """Test new CLI arguments for docling-serve."""

    def test_gpu_flag_is_parsed(self):
        """Test --gpu flag is parsed correctly."""
        with patch.object(sys, "argv", ["mdify", "--gpu", "test.pdf"]):
            args = parse_args()
            assert args.gpu is True
            assert args.input == "test.pdf"

    def test_gpu_flag_default_false(self):
        """Test --gpu flag defaults to False."""
        with patch.object(sys, "argv", ["mdify", "test.pdf"]):
            args = parse_args()
            assert args.gpu is False

    def test_port_argument_default(self):
        """Test --port argument has correct default."""
        with patch.object(sys, "argv", ["mdify", "test.pdf"]):
            args = parse_args()
            assert args.port == 5001

    def test_port_argument_custom(self):
        """Test --port argument accepts custom value."""
        with patch.object(sys, "argv", ["mdify", "--port", "8080", "test.pdf"]):
            args = parse_args()
            assert args.port == 8080

    def test_port_argument_invalid_type(self):
        """Test --port argument rejects non-integer values."""
        with patch.object(sys, "argv", ["mdify", "--port", "invalid", "test.pdf"]):
            with pytest.raises(SystemExit):
                parse_args()

    def test_mask_flag_still_exists(self):
        """Test --mask flag still exists (for deprecation warning)."""
        with patch.object(sys, "argv", ["mdify", "--mask", "test.pdf"]):
            args = parse_args()
            assert args.mask is True

    def test_gpu_and_port_together(self):
        """Test --gpu and --port work together."""
        with patch.object(
            sys, "argv", ["mdify", "--gpu", "--port", "9000", "test.pdf"]
        ):
            args = parse_args()
            assert args.gpu is True
            assert args.port == 9000
            assert args.input == "test.pdf"

    def test_port_argument_high_number(self):
        """Test --port accepts high port numbers."""
        with patch.object(sys, "argv", ["mdify", "--port", "65535", "test.pdf"]):
            args = parse_args()
            assert args.port == 65535


class TestYesFlag:
    """Test --yes / -y flag for skipping confirmation prompts."""

    def test_yes_flag_default_false(self):
        """Test --yes flag defaults to False."""
        with patch.object(sys, "argv", ["mdify", "test.pdf"]):
            args = parse_args()
            assert args.yes is False

    def test_yes_short_flag(self):
        """Test -y flag sets args.yes to True."""
        with patch.object(sys, "argv", ["mdify", "-y", "test.pdf"]):
            args = parse_args()
            assert args.yes is True
            assert args.input == "test.pdf"

    def test_yes_long_flag(self):
        """Test --yes flag sets args.yes to True."""
        with patch.object(sys, "argv", ["mdify", "--yes", "test.pdf"]):
            args = parse_args()
            assert args.yes is True
            assert args.input == "test.pdf"


class TestCleanupGate:
    """Tests for cleanup gating behavior in main()."""

    def test_cleanup_failure_blocks_when_not_confirmed(self, tmp_path, monkeypatch):
        """Main should abort if cleanup fails and user does not confirm."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        summary = CleanupSummary(
            target="local",
            runtime="docker",
            stopped_count=0,
            removed_count=0,
            failures=[CleanupFailure("mdify-serve-abc", "stop", "Stop failed", 1)],
        )

        with patch.object(sys, "argv", ["mdify", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="/usr/bin/docker"):
                with patch("mdify.cli.check_image_exists", return_value=True):
                    with patch("mdify.cli.get_files_to_convert", return_value=[test_file]):
                        with patch("mdify.cli.validate_memory_availability", return_value=(True, "")):
                            with patch("mdify.cli.cleanup_managed_containers", return_value=summary):
                                with patch("mdify.cli.confirm_proceed", return_value=False):
                                    from mdify.cli import main

                                    result = main()
                                    assert result == 130

    def test_remote_cleanup_failure_blocks_when_not_confirmed(self, tmp_path):
        """Remote cleanup failure should abort before starting remote container."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", [
            "mdify",
            "--remote-host",
            "example.com",
            "--remote-skip-ssh-config",
            str(test_file),
        ]):
            args = parse_args()

        class FakeSSHClient:
            def __init__(self, config):
                self.config = config

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            async def validate_remote_resources(self):
                return {
                    "can_connect": True,
                    "work_dir_writable": True,
                    "container_runtime_available": True,
                    "disk_space_min_5gb": True,
                    "memory_min_2gb": True,
                }

            async def check_container_runtime(self):
                return "docker"

            async def run_command(self, cmd, timeout=None):
                return ("", "", 0)

        summary = CleanupSummary(
            target="remote",
            runtime="docker",
            failures=[CleanupFailure("mdify-remote-1", "stop", "Stop failed", 1)],
        )

        with patch("mdify.ssh.AsyncSSHClient", FakeSSHClient):
            with patch("mdify.ssh.remote_container.cleanup_managed_containers", new=AsyncMock(return_value=summary)):
                with patch("mdify.cli.get_files_to_convert", return_value=[test_file]):
                    with patch("mdify.cli.confirm_proceed", return_value=False):
                        result = main_async_remote(args)
                        assert result == 130


class TestCleanupSummaryOutput:
    """Tests for cleanup summary output and confirmation handling."""

    def test_print_cleanup_summary_includes_failures(self, capsys):
        color = Colorizer(sys.stderr)
        summary = CleanupSummary(
            target="local",
            runtime="docker",
            stopped_count=1,
            removed_count=2,
            failures=[CleanupFailure("mdify-serve-abc", "remove", "Remove failed", 1)],
        )

        _print_cleanup_summary(summary, color, quiet=False)
        captured = capsys.readouterr()
        assert "Failures: 1" in captured.err
        assert "mdify-serve-abc" in captured.err

    def test_handle_cleanup_failure_prompts_confirmation(self):
        color = Colorizer(sys.stderr)
        summary = CleanupSummary(
            target="local",
            runtime="docker",
            failures=[CleanupFailure("mdify-serve-abc", "stop", "Stop failed", 1)],
        )

        args = Mock()
        args.yes = False

        with patch("mdify.cli.confirm_proceed", return_value=True) as mock_confirm:
            proceed = _handle_cleanup_failure(summary, args, color)

        assert proceed is True
        assert summary.proceeded_after_failure is True
        assert mock_confirm.called


class TestPathResolution:
    """Tests for path resolution error handling."""

    def test_input_path_permission_error_fallback(self, tmp_path, monkeypatch):
        """Test that main() exits with code 2 when detect_runtime returns None.

        Note: With detect_runtime mocked to None, main() returns 2 at line 562
        BEFORE reaching path resolution code (lines 584-592). This test verifies
        the runtime-missing exit path, not the PermissionError fallback.
        The PermissionError fallback in path resolution is defensive coding that
        would only be exercised if runtime detection succeeds.

        MDIFY_NO_UPDATE_CHECK=1 prevents check_for_update() from hitting network.
        """
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        original_resolve = Path.resolve

        def mock_resolve(self, strict=False):
            if "test.pdf" in str(self):
                raise PermissionError("Operation not permitted")
            return original_resolve(self, strict=strict)

        with patch.object(Path, "resolve", mock_resolve):
            with patch.object(sys, "argv", ["mdify", str(test_file)]):
                with patch("mdify.cli.detect_runtime", return_value=None):
                    from mdify.cli import main

                    result = main()
                    assert result == 2


class TestUtilityFunctions:
    """Tests for utility formatting functions."""

    def test_format_size_bytes(self):
        """Test format_size with value < 1024 returns bytes."""
        result = format_size(512)
        assert result == "512 B"

    def test_format_size_kilobytes(self):
        """Test format_size with value >= 1024 returns KB."""
        result = format_size(2048)
        assert result == "2.0 KB"

    def test_format_size_megabytes(self):
        """Test format_size with value >= 1MB returns MB."""
        result = format_size(2097152)
        assert result == "2.0 MB"

    def test_format_size_gigabytes(self):
        """Test format_size with value >= 1GB returns GB."""
        result = format_size(1073741824)
        assert result == "1.0 GB"

    def test_format_size_zero(self):
        """Test format_size with zero bytes."""
        result = format_size(0)
        assert result == "0 B"

    def test_format_size_exact_boundary(self):
        """Test format_size at exact 1KB boundary."""
        result = format_size(1024)
        assert result == "1.0 KB"

    def test_format_duration_seconds(self):
        """Test format_duration with value < 60 returns seconds."""
        result = format_duration(45.5)
        assert result == "45.5s"

    def test_format_duration_minutes(self):
        """Test format_duration with value >= 60 returns minutes and seconds."""
        result = format_duration(125)
        assert result == "2m 5s"

    def test_format_duration_hours(self):
        """Test format_duration with value >= 3600 returns hours, minutes, and seconds."""
        result = format_duration(3725)
        assert result == "1h 2m 5s"

    def test_format_duration_zero(self):
        """Test format_duration with zero seconds."""
        result = format_duration(0)
        assert result == "0.0s"

    def test_format_duration_exact_minute(self):
        """Test format_duration at exact 60-second boundary."""
        result = format_duration(60)
        assert result == "1m 0s"


class TestGetFreeSpace:
    """Tests for get_free_space utility function."""

    def test_free_space_success(self):
        """Test get_free_space successfully returns free bytes from shutil.disk_usage."""
        from mdify.cli import get_free_space

        mock_usage = Mock()
        mock_usage.free = 1073741824

        with patch("mdify.cli.shutil.disk_usage", return_value=mock_usage):
            result = get_free_space("/tmp")
            assert result == 1073741824

    def test_free_space_path_not_exists(self):
        """Test get_free_space returns 0 for nonexistent path."""
        from mdify.cli import get_free_space

        with patch("mdify.cli.shutil.disk_usage", side_effect=FileNotFoundError()):
            result = get_free_space("/nonexistent/path/that/does/not/exist")
            assert result == 0

    def test_free_space_oserror(self):
        """Test get_free_space returns 0 on OSError (permission denied, etc)."""
        from mdify.cli import get_free_space

        with patch(
            "mdify.cli.shutil.disk_usage", side_effect=OSError("Permission denied")
        ):
            result = get_free_space("/restricted/path")
            assert result == 0


class TestVersionComparison:
    """Tests for version comparison logic."""

    def test_remote_newer_major(self):
        """Test that major version increase returns True."""
        result = _compare_versions("1.0.0", "2.0.0")
        assert result is True

    def test_remote_newer_minor(self):
        """Test that minor version increase returns True."""
        result = _compare_versions("1.0.0", "1.1.0")
        assert result is True

    def test_remote_newer_patch(self):
        """Test that patch version increase returns True."""
        result = _compare_versions("1.0.0", "1.0.1")
        assert result is True

    def test_same_version(self):
        """Test that same versions return False."""
        result = _compare_versions("1.0.0", "1.0.0")
        assert result is False

    def test_current_newer(self):
        """Test that current version newer than remote returns False."""
        result = _compare_versions("2.0.0", "1.0.0")
        assert result is False

    def test_different_length_versions(self):
        """Test that different length versions are padded and compared correctly."""
        result = _compare_versions("1.0", "1.0.0")
        assert result is False

    def test_invalid_current_version(self):
        """Test that invalid current version returns False (graceful failure)."""
        result = _compare_versions("invalid", "1.0.0")
        assert result is False

    def test_invalid_remote_version(self):
        """Test that invalid remote version returns False (graceful failure)."""
        result = _compare_versions("1.0.0", "invalid")
        assert result is False


class TestVersionChecking:
    """Tests for version checking functions."""

    # =========================================================================
    # _get_remote_version tests (4 tests)
    # =========================================================================

    def test_get_remote_version_success(self):
        """Test successful version fetch from PyPI."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"info": {"version": "1.2.3"}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            result = _get_remote_version()
        assert result == "1.2.3"

    def test_get_remote_version_timeout(self):
        """Test timeout handling returns None."""
        with patch("mdify.cli.urlopen", side_effect=URLError("timeout")):
            result = _get_remote_version()
        assert result is None

    def test_get_remote_version_invalid_json(self):
        """Test invalid JSON response returns None."""
        mock_response = Mock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            result = _get_remote_version()
        assert result is None

    def test_get_remote_version_missing_version(self):
        """Test missing version key returns None."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"info": {}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            result = _get_remote_version()
        assert result is None

    # =========================================================================
    # _should_check_for_update tests (5 tests)
    # =========================================================================

    def test_should_check_env_disabled(self, monkeypatch):
        """Test returns False when MDIFY_NO_UPDATE_CHECK=1."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        result = _should_check_for_update()
        assert result is False

    def test_should_check_no_file(self, isolated_mdify_home):
        """Test returns True when .last_check doesn't exist."""
        result = _should_check_for_update()
        assert result is True

    def test_should_check_recent(self, isolated_mdify_home):
        """Test returns False when last check was recent (< 24h)."""
        fake_home, fake_last_check = isolated_mdify_home
        fake_home.mkdir(parents=True)
        fake_last_check.write_text("1000000")  # timestamp in past
        with patch("mdify.cli.time.time", return_value=1000000 + 3600):  # 1 hour later
            result = _should_check_for_update()
        assert result is False  # Less than CHECK_INTERVAL_SECONDS (86400)

    def test_should_check_old(self, isolated_mdify_home):
        """Test returns True when last check was > 24h ago."""
        fake_home, fake_last_check = isolated_mdify_home
        fake_home.mkdir(parents=True)
        fake_last_check.write_text("1000000")  # timestamp in past
        with patch("mdify.cli.time.time", return_value=1000000 + 90000):  # 25h later
            result = _should_check_for_update()
        assert result is True

    def test_should_check_corrupted_file(self, isolated_mdify_home):
        """Test returns True when .last_check contains invalid data."""
        fake_home, fake_last_check = isolated_mdify_home
        fake_home.mkdir(parents=True)
        fake_last_check.write_text("garbage")  # invalid timestamp
        result = _should_check_for_update()
        assert result is True

    # =========================================================================
    # _update_last_check_time tests (2 tests)
    # =========================================================================

    def test_update_last_check_creates_file(self, isolated_mdify_home):
        """Test creates .last_check file with correct timestamp."""
        fake_home, fake_last_check = isolated_mdify_home
        known_time = 1234567890.123
        with patch("mdify.cli.time.time", return_value=known_time):
            _update_last_check_time()
        assert fake_last_check.exists()
        content = fake_last_check.read_text()
        assert float(content) == known_time

    def test_update_last_check_oserror_no_crash(self, isolated_mdify_home):
        """Test that OSError on mkdir doesn't crash the function."""
        with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
            # Should not raise - function catches OSError
            _update_last_check_time()
        # Function returns None on error, test passes if no exception

    # =========================================================================
    # check_for_update tests (5 tests)
    # =========================================================================

    def test_check_for_update_skip_check(self, monkeypatch):
        """Test check is skipped when MDIFY_NO_UPDATE_CHECK=1."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        with patch("mdify.cli.urlopen") as mock_urlopen:
            check_for_update(force=False)
        mock_urlopen.assert_not_called()  # Should skip network call

    def test_check_for_update_newer_available(
        self, isolated_mdify_home, capsys, monkeypatch
    ):
        """Test prints update message when newer version available."""
        monkeypatch.setattr("mdify.cli.__version__", "1.0.0")
        mock_response = Mock()
        mock_response.read.return_value = b'{"info": {"version": "2.0.0"}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            check_for_update(force=True)
        captured = capsys.readouterr()
        assert "A new version" in captured.out
        assert "2.0.0" in captured.out

    def test_check_for_update_up_to_date_silent(
        self, isolated_mdify_home, capsys, monkeypatch
    ):
        """Test no output when force=False and versions match."""
        monkeypatch.setattr("mdify.cli.__version__", "1.0.0")
        mock_response = Mock()
        mock_response.read.return_value = b'{"info": {"version": "1.0.0"}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            check_for_update(force=False)
        captured = capsys.readouterr()
        assert captured.out == ""  # No output when force=False and up to date

    def test_check_for_update_force_shows_current(
        self, isolated_mdify_home, capsys, monkeypatch
    ):
        """Test prints 'up to date' message when force=True and versions match."""
        monkeypatch.setattr("mdify.cli.__version__", "1.0.0")
        mock_response = Mock()
        mock_response.read.return_value = b'{"info": {"version": "1.0.0"}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        with patch("mdify.cli.urlopen", return_value=mock_response):
            check_for_update(force=True)
        captured = capsys.readouterr()
        assert "up to date" in captured.out

    def test_check_for_update_force_network_error(self, capsys):
        """Test sys.exit(1) when force=True and network error."""
        with patch("mdify.cli.urlopen", side_effect=URLError("Network error")):
            with pytest.raises(SystemExit) as exc_info:
                check_for_update(force=True)
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Failed to check for updates" in captured.err


class TestFileHandling:
    """Tests for file handling functions."""

    # =========================================================================
    # Tests for get_files_to_convert (8 tests)
    # =========================================================================

    def test_single_file(self, tmp_path):
        """Test get_files_to_convert with single file."""
        pdf_file = tmp_path / "doc.pdf"
        pdf_file.touch()
        result = get_files_to_convert(pdf_file, mask="*", recursive=False)
        assert result == [pdf_file]

    def test_directory_non_recursive(self, tmp_path):
        """Test directory scan is non-recursive by default."""
        (tmp_path / "doc1.pdf").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "doc2.pdf").touch()
        result = get_files_to_convert(tmp_path, mask="*", recursive=False)
        assert len(result) == 1  # Only top-level doc1.pdf
        assert result[0].name == "doc1.pdf"

    def test_directory_recursive(self, tmp_path):
        """Test directory scan with recursive flag."""
        (tmp_path / "doc1.pdf").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "doc2.pdf").touch()
        result = get_files_to_convert(tmp_path, mask="*", recursive=True)
        assert len(result) == 2  # Both files

    def test_glob_pattern(self, tmp_path):
        """Test glob pattern filtering."""
        (tmp_path / "doc.pdf").touch()
        (tmp_path / "doc.docx").touch()
        result = get_files_to_convert(tmp_path, mask="*.pdf", recursive=False)
        assert len(result) == 1
        assert result[0].name == "doc.pdf"

    def test_hidden_files_excluded(self, tmp_path):
        """Hidden files are excluded even if they have supported extensions."""
        (tmp_path / "visible.pdf").touch()
        (tmp_path / ".hidden.pdf").touch()  # Hidden file with supported extension
        # Note: glob("*") doesn't match dotfiles, so .hidden.pdf won't be in initial set
        # The function's explicit filter `not f.name.startswith(".")` is a safety net
        result = get_files_to_convert(tmp_path, mask="*", recursive=False)
        assert len(result) == 1
        assert result[0].name == "visible.pdf"

    def test_unsupported_extensions_excluded(self, tmp_path):
        """Files with unsupported extensions are filtered out."""
        (tmp_path / "doc.pdf").touch()  # Supported
        (tmp_path / "readme.txt").touch()  # NOT in SUPPORTED_EXTENSIONS
        result = get_files_to_convert(tmp_path, mask="*", recursive=False)
        assert len(result) == 1
        assert result[0].name == "doc.pdf"

    def test_skipped_extensions_excluded(self, tmp_path):
        """Files with skipped extensions (.md, .json, .xml) are filtered out."""
        (tmp_path / "doc.pdf").touch()  # Should be included
        (tmp_path / "readme.md").touch()  # Skipped - already markdown
        (tmp_path / "config.json").touch()  # Skipped - structured data
        (tmp_path / "data.xml").touch()  # Skipped - structured data
        result = get_files_to_convert(tmp_path, mask="*", recursive=False)
        assert len(result) == 1
        assert result[0].name == "doc.pdf"

    def test_empty_directory(self, tmp_path):
        """Test empty directory returns empty list."""
        result = get_files_to_convert(tmp_path, mask="*", recursive=False)
        assert result == []

    def test_nonexistent_path(self, tmp_path):
        """Test nonexistent path raises FileNotFoundError."""
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            get_files_to_convert(nonexistent, mask="*", recursive=False)

    # =========================================================================
    # Tests for get_output_path (5 tests)
    # =========================================================================

    def test_output_path_preserves_structure(self, tmp_path):
        """Test output path preserves directory structure when flat=False."""
        input_file = tmp_path / "input" / "sub" / "doc.pdf"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        input_base = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = get_output_path(input_file, input_base, output_dir, flat=False)

        assert result == output_dir / "sub" / "doc.md"

    def test_output_path_flat_mode(self, tmp_path):
        """Test output path with flat mode combines path separators."""
        input_file = tmp_path / "input" / "sub" / "doc.pdf"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        input_base = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = get_output_path(input_file, input_base, output_dir, flat=True)

        assert result == output_dir / "sub_doc.md"

    def test_output_path_flat_mode_root_file(self, tmp_path):
        """Test output path with flat mode for file at root."""
        input_file = tmp_path / "input" / "doc.pdf"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        input_base = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = get_output_path(input_file, input_base, output_dir, flat=True)

        assert result == output_dir / "doc.md"

    def test_output_path_deeply_nested(self, tmp_path):
        """Test output path with deeply nested directory structure in flat mode."""
        input_file = tmp_path / "input" / "a" / "b" / "c" / "doc.pdf"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        input_base = tmp_path / "input"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = get_output_path(input_file, input_base, output_dir, flat=True)

        assert result == output_dir / "a_b_c_doc.md"

    def test_output_path_file_not_relative(self, tmp_path):
        """Test output path when input file is outside input_base."""
        input_file = tmp_path / "other" / "doc.pdf"
        input_file.parent.mkdir(parents=True)
        input_file.touch()
        input_base = tmp_path / "base"
        input_base.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        result = get_output_path(input_file, input_base, output_dir, flat=False)

        # Per mdify/cli.py:384, when relative_to fails, returns output_dir / f"{stem}.md"
        assert result == output_dir / "doc.md"


class TestIsDaemonRunning:
    """Tests for is_daemon_running() function."""

    def test_daemon_running_returns_true(self):
        """Test is_daemon_running returns True when daemon is responsive."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = is_daemon_running("/usr/bin/docker")
        assert result is True

    def test_daemon_not_running_returns_false(self):
        """Test is_daemon_running returns False when daemon is not responsive."""
        mock_result = Mock()
        mock_result.returncode = 1
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = is_daemon_running("/usr/bin/docker")
        assert result is False

    def test_daemon_timeout_returns_false(self):
        """Test is_daemon_running returns False on timeout."""
        with patch("mdify.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = is_daemon_running("/usr/bin/docker")
        assert result is False

    def test_daemon_oserror_returns_false(self):
        """Test is_daemon_running returns False on OSError."""
        with patch("mdify.cli.subprocess.run", side_effect=OSError("No such file")):
            result = is_daemon_running("/usr/bin/nonexistent")
        assert result is False

    def test_apple_container_daemon_running(self):
        """Test is_daemon_running uses 'system status' for Apple Container."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = is_daemon_running("/usr/local/bin/container")
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/local/bin/container", "system", "status"],
            capture_output=True,
            timeout=5,
            check=False,
        )

    def test_apple_container_daemon_not_running(self):
        """Test is_daemon_running returns False when Apple Container daemon not running."""
        mock_result = Mock()
        mock_result.returncode = 1
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = is_daemon_running("/usr/local/bin/container")
        assert result is False
        mock_run.assert_called_once_with(
            ["/usr/local/bin/container", "system", "status"],
            capture_output=True,
            timeout=5,
            check=False,
        )


class TestContainerRuntime:
    """Tests for container runtime functions."""

    def test_image_exists_returns_true(self):
        """Test check_image_exists returns True when image exists."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = check_image_exists("/usr/bin/docker", "test-image:latest")
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "image", "inspect", "test-image:latest"],
            capture_output=True,
            check=False,
        )

    def test_image_not_exists_returns_false(self):
        """Test check_image_exists returns False when image doesn't exist."""
        mock_result = Mock()
        mock_result.returncode = 1
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = check_image_exists("/usr/bin/docker", "test-image:latest")
        assert result is False
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "image", "inspect", "test-image:latest"],
            capture_output=True,
            check=False,
        )

    def test_image_check_oserror_returns_false(self):
        """Test check_image_exists returns False on OSError."""
        with patch(
            "mdify.cli.subprocess.run", side_effect=OSError("Command not found")
        ):
            result = check_image_exists("/usr/bin/docker", "test-image:latest")
        assert result is False

    def test_pull_success(self):
        """Test pull_image returns True on successful pull."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = pull_image("/usr/bin/docker", "test-image", quiet=True)
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "pull", "test-image"],
            capture_output=True,
            check=False,
        )

    def test_pull_failure(self):
        """Test pull_image returns False on failed pull."""
        mock_result = Mock()
        mock_result.returncode = 1
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = pull_image("/usr/bin/docker", "test-image", quiet=True)
        assert result is False
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "pull", "test-image"],
            capture_output=True,
            check=False,
        )

    def test_pull_quiet_mode(self):
        """Test pull_image with quiet=True uses capture_output=True."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = pull_image("/usr/bin/docker", "test-image", quiet=True)
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "pull", "test-image"],
            capture_output=True,
            check=False,
        )

    def test_pull_verbose_mode(self, capsys):
        """Test pull_image with quiet=False prints and uses capture_output=False."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = pull_image("/usr/bin/docker", "test-image", quiet=False)
        assert result is True
        captured = capsys.readouterr()
        assert "Pulling image: test-image" in captured.out
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "pull", "test-image"],
            capture_output=False,
            check=False,
        )

    def test_pull_oserror(self, capsys):
        """Test pull_image returns False and prints error on OSError."""
        with patch(
            "mdify.cli.subprocess.run", side_effect=OSError("Command not found")
        ):
            result = pull_image("/usr/bin/docker", "test-image", quiet=False)
        assert result is False
        captured = capsys.readouterr()
        assert "Error pulling image" in captured.err

    def test_apple_container_pull_success(self):
        """Test pull_image uses 'image pull' for Apple Container."""
        mock_result = Mock()
        mock_result.returncode = 0
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = pull_image("/usr/local/bin/container", "test-image", quiet=True)
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/local/bin/container", "image", "pull", "test-image"],
            capture_output=True,
            check=False,
        )

    def test_apple_container_image_exists(self):
        """Test check_image_exists uses 'image list' for Apple Container."""
        mock_result = Mock()
        mock_result.returncode = 0
        # Use actual Apple Container response format with 'reference' field
        mock_result.stdout = json.dumps([
            {
                "reference": "ghcr.io/docling-project/docling-serve-cpu:main",
                "descriptor": {
                    "size": 1609,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "digest": "sha256:25e82dfa30371d17a0af17edc42261a4b9bedb37f0f337887c366184bc3ee291"
                }
            }
        ]).encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = check_image_exists("/usr/local/bin/container", "ghcr.io/docling-project/docling-serve-cpu:main")
        assert result is True
        mock_run.assert_called_once_with(
            ["/usr/local/bin/container", "image", "list", "--format", "json"],
            capture_output=True,
            check=False,
        )

    def test_apple_container_image_not_exists(self):
        """Test check_image_exists returns False when image not in list."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {
                "reference": "ghcr.io/other-project/other-image:latest",
                "descriptor": {
                    "size": 1234,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "digest": "sha256:abcd1234"
                }
            }
        ]).encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = check_image_exists("/usr/local/bin/container", "ghcr.io/docling-project/docling-serve-cpu:main")
        assert result is False


class TestGetStorageRoot:
    """Tests for get_storage_root() function."""

    def test_docker_storage_root_success(self):
        """Test get_storage_root returns Docker storage root on success."""
        from mdify.cli import get_storage_root

        mock_result = Mock()
        mock_result.stdout = b"/var/lib/docker\n"
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = get_storage_root("docker")
        assert result == "/var/lib/docker"
        mock_run.assert_called_once_with(
            ["docker", "system", "info", "--format", "{{.DockerRootDir}}"],
            capture_output=True,
            check=False,
        )

    def test_podman_storage_root_success(self):
        """Test get_storage_root returns Podman storage root on success."""
        from mdify.cli import get_storage_root

        podman_output = json.dumps(
            {"store": {"graphRoot": "/var/lib/containers/storage"}}
        )
        mock_result = Mock()
        mock_result.stdout = podman_output.encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = get_storage_root("podman")
        assert result == "/var/lib/containers/storage"
        mock_run.assert_called_once_with(
            ["podman", "info", "--format", "json"],
            capture_output=True,
            check=False,
        )

    def test_storage_root_command_fails(self):
        """Test get_storage_root returns None when command fails."""
        from mdify.cli import get_storage_root

        mock_result = Mock()
        mock_result.stdout = b""
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = get_storage_root("docker")
        assert result is None

    def test_storage_root_oserror(self):
        """Test get_storage_root returns None on OSError."""
        from mdify.cli import get_storage_root

        with patch(
            "mdify.cli.subprocess.run", side_effect=OSError("Command not found")
        ):
            result = get_storage_root("docker")
        assert result is None

    def test_docker_storage_root_with_full_path(self):
        """Test get_storage_root works with full path to Docker executable."""
        from mdify.cli import get_storage_root

        mock_result = Mock()
        mock_result.stdout = b"/var/lib/docker\n"
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = get_storage_root("/usr/bin/docker")
        assert result == "/var/lib/docker"
        mock_run.assert_called_once_with(
            ["/usr/bin/docker", "system", "info", "--format", "{{.DockerRootDir}}"],
            capture_output=True,
            check=False,
        )

    def test_podman_storage_root_with_full_path(self):
        """Test get_storage_root works with full path to Podman executable."""
        from mdify.cli import get_storage_root

        podman_output = json.dumps(
            {"store": {"graphRoot": "/var/lib/containers/storage"}}
        )
        mock_result = Mock()
        mock_result.stdout = podman_output.encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result) as mock_run:
            result = get_storage_root("/usr/local/bin/podman")
        assert result == "/var/lib/containers/storage"
        mock_run.assert_called_once_with(
            ["/usr/local/bin/podman", "info", "--format", "json"],
            capture_output=True,
            check=False,
        )

    def test_podman_storage_root_invalid_json(self):
        """Test get_storage_root returns None when Podman returns invalid JSON."""
        from mdify.cli import get_storage_root

        mock_result = Mock()
        mock_result.stdout = b"invalid json {{"
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = get_storage_root("podman")
        assert result is None

    def test_orbstack_storage_root(self, monkeypatch):
        """Test get_storage_root returns OrbStack storage root."""
        from mdify.cli import get_storage_root

        home = "/Users/testuser"
        monkeypatch.setenv("HOME", home)
        result = get_storage_root("/usr/local/bin/orbstack")
        assert result == f"{home}/.orbstack"

    def test_colima_storage_root_returns_none(self, monkeypatch):
        """Test get_storage_root returns None for colima (no longer a supported runtime)."""
        from mdify.cli import get_storage_root

        result = get_storage_root("/usr/local/bin/colima")
        assert result is None

    def test_orbstack_storage_root_with_full_path(self, monkeypatch):
        """Test get_storage_root works with full path to OrbStack executable."""
        from mdify.cli import get_storage_root

        home = "/Users/apple"
        monkeypatch.setenv("HOME", home)
        result = get_storage_root("/opt/homebrew/bin/orbstack")
        assert result == f"{home}/.orbstack"

    def test_apple_container_storage_root(self, monkeypatch):
        """Test get_storage_root returns Apple Container storage root."""
        from mdify.cli import get_storage_root

        home = "/Users/testuser"
        monkeypatch.setenv("HOME", home)
        result = get_storage_root("/usr/local/bin/container")
        assert result == f"{home}/Library/Application Support/com.apple.container"

    def test_apple_container_storage_root_with_full_path(self, monkeypatch):
        """Test get_storage_root works with full path to Apple Container executable."""
        from mdify.cli import get_storage_root

        home = "/Users/apple"
        monkeypatch.setenv("HOME", home)
        result = get_storage_root("/opt/homebrew/bin/container")
        assert result == f"{home}/Library/Application Support/com.apple.container"


class TestGetImageSizeEstimate:
    """Tests for get_image_size_estimate function."""

    def test_image_size_success(self):
        """Test get_image_size_estimate returns sum of layer sizes with 50% buffer."""
        manifest_json = {
            "Manifests": [
                {
                    "OCIManifest": {
                        "layers": [
                            {"size": 1000},
                            {"size": 2000},
                        ]
                    }
                },
                {
                    "OCIManifest": {
                        "layers": [
                            {"size": 1500},
                            {"size": 2500},
                        ]
                    }
                },
            ]
        }
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(manifest_json).encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = get_image_size_estimate("/usr/bin/docker", "test-image:latest")
        assert result == 10500

    def test_image_size_command_fails(self):
        """Test get_image_size_estimate returns None when command fails."""
        mock_result = Mock()
        mock_result.returncode = 1
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = get_image_size_estimate("/usr/bin/docker", "test-image:latest")
        assert result is None

    def test_image_size_invalid_json(self):
        """Test get_image_size_estimate returns None on malformed JSON."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = b"invalid json"
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = get_image_size_estimate("/usr/bin/docker", "test-image:latest")
        assert result is None

    def test_image_size_adds_buffer(self):
        """Test get_image_size_estimate applies 50% decompression buffer."""
        manifest_json = {
            "Manifests": [
                {
                    "OCIManifest": {
                        "layers": [
                            {"size": 100},
                        ]
                    }
                },
            ]
        }
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(manifest_json).encode()
        with patch("mdify.cli.subprocess.run", return_value=mock_result):
            result = get_image_size_estimate("/usr/bin/docker", "test-image:latest")
        assert result == 150


class TestConfirmProceed:
    """Tests for confirm_proceed() user confirmation function."""

    def test_confirm_yes(self, capsys):
        """Test confirm_proceed returns True when user enters 'y'."""
        from mdify.cli import confirm_proceed

        with patch("builtins.input", return_value="y"):
            with patch("sys.stdin.isatty", return_value=True):
                result = confirm_proceed("Continue?")
        assert result is True
        captured = capsys.readouterr()
        assert "Continue?" in captured.err
        assert "[y/N]" in captured.err

    def test_confirm_no(self, capsys):
        """Test confirm_proceed returns False when user enters 'n'."""
        from mdify.cli import confirm_proceed

        with patch("builtins.input", return_value="n"):
            with patch("sys.stdin.isatty", return_value=True):
                result = confirm_proceed("Continue?")
        assert result is False
        captured = capsys.readouterr()
        assert "Continue?" in captured.err

    def test_confirm_empty_default_no(self, capsys):
        """Test confirm_proceed returns False when user presses Enter (empty input)."""
        from mdify.cli import confirm_proceed

        with patch("builtins.input", return_value=""):
            with patch("sys.stdin.isatty", return_value=True):
                result = confirm_proceed("Continue?", default_no=True)
        assert result is False
        captured = capsys.readouterr()
        assert "[y/N]" in captured.err

    def test_confirm_non_tty(self):
        """Test confirm_proceed returns False immediately when stdin is not a TTY."""
        from mdify.cli import confirm_proceed

        with patch("sys.stdin.isatty", return_value=False):
            with patch("builtins.input") as mock_input:
                result = confirm_proceed("Continue?")
        assert result is False
        mock_input.assert_not_called()


class TestSpaceCheckIntegration:
    """Integration tests for disk space checking in main() function."""

    def test_space_check_skipped_when_pull_never(self, tmp_path, monkeypatch):
        """Test that space check is skipped entirely when --pull=never."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", ["mdify", "--pull=never", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=True):
                    with patch("mdify.cli.get_storage_root") as mock_storage:
                        with patch("mdify.cli.DoclingContainer"):
                            from mdify.cli import main

                            main()
                            # Space check should NOT run because pull=never
                            mock_storage.assert_not_called()

    def test_space_check_skipped_when_image_exists(self, tmp_path, monkeypatch):
        """Test that space check is skipped when image exists and pull=missing."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", ["mdify", "--pull=missing", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=True):
                    with patch("mdify.cli.get_storage_root") as mock_storage:
                        with patch("mdify.cli.DoclingContainer"):
                            from mdify.cli import main

                            main()
                            # Space check should NOT run because image exists
                            mock_storage.assert_not_called()

    def test_space_check_warns_insufficient_space(self, tmp_path, monkeypatch, capsys):
        """Test that warning is printed when free space < image size."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", ["mdify", "--pull=always", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=False):
                    with patch(
                        "mdify.cli.get_storage_root", return_value="/var/lib/docker"
                    ):
                        with patch(
                            "mdify.cli.get_image_size_estimate",
                            return_value=5_000_000_000,
                        ):
                            with patch(
                                "mdify.cli.get_free_space", return_value=3_000_000_000
                            ):
                                with patch(
                                    "mdify.cli.confirm_proceed", return_value=True
                                ):
                                    with patch(
                                        "mdify.cli.pull_image", return_value=True
                                    ):
                                        with patch("mdify.cli.DoclingContainer"):
                                            from mdify.cli import main

                                            main()
                                            captured = capsys.readouterr()
                                            assert (
                                                "Not enough free disk space"
                                                in captured.err
                                            )

    def test_space_check_warns_low_remaining(self, tmp_path, monkeypatch, capsys):
        """Test that warning is printed when remaining space < 1GB."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        # 2GB image, 2.5GB free → remaining = 0.5GB (< 1GB threshold)
        with patch.object(sys, "argv", ["mdify", "--pull=always", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=False):
                    with patch(
                        "mdify.cli.get_storage_root", return_value="/var/lib/docker"
                    ):
                        with patch(
                            "mdify.cli.get_image_size_estimate",
                            return_value=2_000_000_000,
                        ):
                            with patch(
                                "mdify.cli.get_free_space", return_value=2_500_000_000
                            ):
                                with patch(
                                    "mdify.cli.confirm_proceed", return_value=True
                                ):
                                    with patch(
                                        "mdify.cli.pull_image", return_value=True
                                    ):
                                        with patch("mdify.cli.DoclingContainer"):
                                            from mdify.cli import main

                                            main()
                                            captured = capsys.readouterr()
                                            assert (
                                                "Less than 1 GB would remain"
                                                in captured.err
                                            )

    def test_space_check_yes_flag_skips_prompt(self, tmp_path, monkeypatch):
        """Test that --yes flag skips confirmation prompt."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(
            sys, "argv", ["mdify", "--yes", "--pull=always", str(test_file)]
        ):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=False):
                    with patch(
                        "mdify.cli.get_storage_root", return_value="/var/lib/docker"
                    ):
                        with patch(
                            "mdify.cli.get_image_size_estimate",
                            return_value=5_000_000_000,
                        ):
                            with patch(
                                "mdify.cli.get_free_space", return_value=3_000_000_000
                            ):
                                with patch("mdify.cli.confirm_proceed") as mock_confirm:
                                    with patch(
                                        "mdify.cli.pull_image", return_value=True
                                    ):
                                        with patch("mdify.cli.DoclingContainer"):
                                            from mdify.cli import main

                                            main()
                                            # confirm_proceed should NOT be called with --yes
                                            mock_confirm.assert_not_called()

    def test_space_check_non_tty_no_yes_aborts(self, tmp_path, monkeypatch, capsys):
        """Test that non-TTY without --yes prints error and exits with code 1."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", ["mdify", "--pull=always", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=False):
                    with patch(
                        "mdify.cli.get_storage_root", return_value="/var/lib/docker"
                    ):
                        with patch(
                            "mdify.cli.get_image_size_estimate",
                            return_value=5_000_000_000,
                        ):
                            with patch(
                                "mdify.cli.get_free_space", return_value=3_000_000_000
                            ):
                                with patch("sys.stdin.isatty", return_value=False):
                                    from mdify.cli import main

                                    result = main()
                                    assert result == 1
                                    captured = capsys.readouterr()
                                    assert "Not enough free disk space" in captured.err
                                    assert (
                                        "Run with --yes to proceed anyway"
                                        in captured.err
                                    )

    def test_space_check_user_declines_exits_130(self, tmp_path, monkeypatch):
        """Test that user declining confirmation exits with code 130."""
        monkeypatch.setenv("MDIFY_NO_UPDATE_CHECK", "1")
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        with patch.object(sys, "argv", ["mdify", "--pull=always", str(test_file)]):
            with patch("mdify.cli.detect_runtime", return_value="docker"):
                with patch("mdify.cli.check_image_exists", return_value=False):
                    with patch(
                        "mdify.cli.get_storage_root", return_value="/var/lib/docker"
                    ):
                        with patch(
                            "mdify.cli.get_image_size_estimate",
                            return_value=5_000_000_000,
                        ):
                            with patch(
                                "mdify.cli.get_free_space", return_value=3_000_000_000
                            ):
                                with patch(
                                    "mdify.cli.confirm_proceed", return_value=False
                                ):
                                    with patch("sys.stdin.isatty", return_value=True):
                                        from mdify.cli import main

                                        result = main()
                                        assert result == 130
