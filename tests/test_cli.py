"""Tests for mdify CLI runtime detection."""

import sys
from unittest.mock import patch, Mock
import pytest

from mdify.cli import detect_runtime, parse_args


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
