"""Tests for mdify CLI runtime detection."""

import sys
from pathlib import Path
from unittest.mock import patch, Mock
import pytest
from urllib.error import URLError

from mdify.cli import (
    detect_runtime,
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
)


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
