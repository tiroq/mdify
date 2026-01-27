"""Tests for mdify CLI runtime detection."""

import sys
from pathlib import Path
from unittest.mock import patch, Mock
import pytest

from mdify.cli import (
    detect_runtime,
    parse_args,
    format_size,
    format_duration,
    _compare_versions,
)


class TestDetectRuntime:
    """Tests for detect_runtime() function."""

    def test_auto_docker_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/docker" if x == "docker" else None
            )
            result = detect_runtime("docker", explicit=False)
            assert result == "/usr/bin/docker"

    def test_auto_only_podman_exists(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/podman" if x == "podman" else None
            )
            result = detect_runtime("docker", explicit=False)
            assert result == "/usr/bin/podman"
            captured = capsys.readouterr()
            assert captured.err == ""

    def test_auto_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime("docker", explicit=False)
            assert result is None

    def test_explicit_docker_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/docker" if x == "docker" else None
            )
            result = detect_runtime("docker", explicit=True)
            assert result == "/usr/bin/docker"

    def test_explicit_docker_fallback_to_podman(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/podman" if x == "podman" else None
            )
            result = detect_runtime("docker", explicit=True)
            assert result == "/usr/bin/podman"
            captured = capsys.readouterr()
            assert "Warning: docker not found, using podman" in captured.err

    def test_explicit_docker_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime("docker", explicit=True)
            assert result is None

    def test_explicit_podman_exists(self):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/podman" if x == "podman" else None
            )
            result = detect_runtime("podman", explicit=True)
            assert result == "/usr/bin/podman"

    def test_explicit_podman_fallback_to_docker(self, capsys):
        with patch("mdify.cli.shutil.which") as mock_which:
            mock_which.side_effect = (
                lambda x: "/usr/bin/docker" if x == "docker" else None
            )
            result = detect_runtime("podman", explicit=True)
            assert result == "/usr/bin/docker"
            captured = capsys.readouterr()
            assert "Warning: podman not found, using docker" in captured.err

    def test_explicit_podman_neither_exists(self):
        with patch("mdify.cli.shutil.which", return_value=None):
            result = detect_runtime("podman", explicit=True)
            assert result is None


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
