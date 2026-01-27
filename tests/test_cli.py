"""Tests for mdify CLI runtime detection."""

from unittest.mock import patch
from mdify.cli import detect_runtime


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
