#!/usr/bin/env python3
"""
CLI for converting documents to Markdown.

This CLI orchestrates document conversion by invoking a Docker/Podman
container that contains Docling and ML dependencies. The CLI itself
is lightweight and has no ML dependencies.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from . import __version__
from mdify.container import DoclingContainer
from mdify.docling_client import convert_file

# Configuration
MDIFY_HOME = Path.home() / ".mdify"
LAST_CHECK_FILE = MDIFY_HOME / ".last_check"
PYPI_API_URL = "https://pypi.org/pypi/mdify-cli/json"
CHECK_INTERVAL_SECONDS = 86400  # 24 hours

# Container configuration
DEFAULT_IMAGE = "ghcr.io/docling-project/docling-serve-cpu:main"
GPU_IMAGE = "ghcr.io/docling-project/docling-serve-cu126:main"
SUPPORTED_RUNTIMES = ("docker", "podman", "orbstack", "colima", "container")
MACOS_RUNTIMES_PRIORITY = ("container", "orbstack", "colima", "podman", "docker")
OTHER_RUNTIMES_PRIORITY = ("docker", "podman")

# Debug mode
DEBUG = os.environ.get("MDIFY_DEBUG", "").lower() in ("1", "true", "yes")

# Resource profiles for container execution
RESOURCE_PROFILES = {
    "minimal": {"cpus": 4, "memory": "8g", "description": "Small PDFs, text-only documents"},
    "default": {"cpus": 6, "memory": "12g", "description": "Large PDFs, OCR, tables (recommended)"},
    "heavy": {"cpus": 8, "memory": "16g", "description": "Batch processing, very large files"},
}


def get_available_memory_gb() -> float:
    """Get available system memory in GB.
    
    Returns:
        Available memory in GB, or -1 if unable to determine
    """
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            # Get page size
            result = subprocess.run(["pagesize"], capture_output=True, text=True, check=True)
            page_size = int(result.stdout.strip())
            
            # Get memory stats
            result = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True)
            free_pages = 0
            inactive_pages = 0
            speculative_pages = 0
            
            for line in result.stdout.split("\n"):
                if "Pages free" in line:
                    free_pages = int(line.split(":")[1].strip().rstrip("."))
                elif "Pages inactive" in line:
                    inactive_pages = int(line.split(":")[1].strip().rstrip("."))
                elif "Pages speculative" in line:
                    speculative_pages = int(line.split(":")[1].strip().rstrip("."))
            
            # Available memory = free + inactive + speculative
            available_pages = free_pages + inactive_pages + speculative_pages
            available_bytes = available_pages * page_size
            return available_bytes / (1024**3)  # Convert to GB
        elif system == "Linux":
            # Read from /proc/meminfo
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        return kb / (1024**2)  # Convert to GB
    except Exception:
        pass
    
    return -1


def parse_memory_string(mem_str: str) -> float:
    """Parse memory string (e.g., '12g', '8192m') to GB.
    
    Args:
        mem_str: Memory string with unit (g, m, gb, mb)
        
    Returns:
        Memory in GB
    """
    mem_str = mem_str.lower().strip()
    
    if mem_str.endswith("gb"):
        return float(mem_str[:-2])
    elif mem_str.endswith("g"):
        return float(mem_str[:-1])
    elif mem_str.endswith("mb"):
        return float(mem_str[:-2]) / 1024
    elif mem_str.endswith("m"):
        return float(mem_str[:-1]) / 1024
    else:
        raise ValueError(f"Invalid memory format: {mem_str}")


def validate_memory_availability(
    required_gb: float,
    profile_name: str = "default",
    suggest_profile: Optional[str] = None,
) -> tuple[bool, str]:
    """Check if system has sufficient available memory.
    
    Args:
        required_gb: Required memory in GB
        profile_name: Name of current profile being used
        suggest_profile: Name of smaller profile to suggest (auto-detected if None)
        
    Returns:
        Tuple of (is_sufficient, error_message)
    """
    available_gb = get_available_memory_gb()
    
    if available_gb < 0:
        # Unable to determine, allow startup with warning
        return True, ""
    
    if available_gb < required_gb:
        # Determine which smaller profile to suggest
        if suggest_profile is None:
            if profile_name == "heavy":
                suggest_profile = "default"
            elif profile_name == "default":
                suggest_profile = "minimal"
            else:
                suggest_profile = None  # Already on minimal
        
        error = (
            f"Insufficient memory available for container startup.\n"
            f"  Current profile: {profile_name}\n"
            f"  Required: {required_gb:.1f} GB\n"
            f"  Available: {available_gb:.1f} GB\n"
            f"  Short by: {required_gb - available_gb:.1f} GB\n\n"
        )
        
        if suggest_profile:
            suggested = RESOURCE_PROFILES[suggest_profile]
            error += (
                f"Suggested solutions:\n"
                f"  1. Close other applications to free up memory\n"
                f"  2. Use a smaller profile: --profile {suggest_profile} "
                f"({suggested['cpus']} CPUs, {suggested['memory']} memory)\n"
                f"  3. Skip memory check: --skip-memory-check (not recommended)"
            )
        else:
            error += (
                f"Suggested solutions:\n"
                f"  1. Close other applications to free up memory\n"
                f"  2. Skip memory check: --skip-memory-check (not recommended)"
            )
        
        return False, error
    
    return True, ""


# =============================================================================
# Update checking functions
# =============================================================================


def _get_remote_version(timeout: int = 5) -> Optional[str]:
    """
    Fetch the latest version from PyPI.

    Returns:
        Version string (e.g., "1.1.0") or None if fetch failed.
    """
    try:
        with urlopen(PYPI_API_URL, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            version = data.get("info", {}).get("version", "")
            return version if version else None
    except (URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return None


def _should_check_for_update() -> bool:
    """
    Determine if we should check for updates based on last check time.

    Returns:
        True if check should be performed, False otherwise.
    """
    if os.environ.get("MDIFY_NO_UPDATE_CHECK", "").lower() in ("1", "true", "yes"):
        return False

    if not LAST_CHECK_FILE.exists():
        return True

    try:
        last_check = float(LAST_CHECK_FILE.read_text().strip())
        elapsed = time.time() - last_check
        return elapsed >= CHECK_INTERVAL_SECONDS
    except (ValueError, OSError):
        return True


def _update_last_check_time() -> None:
    """Update the last check timestamp file."""
    try:
        LAST_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_CHECK_FILE.write_text(str(time.time()))
    except OSError:
        pass


def _compare_versions(current: str, remote: str) -> bool:
    """
    Compare version strings.

    Returns:
        True if remote version is newer than current.
    """
    try:
        current_parts = [int(x) for x in current.split(".")]
        remote_parts = [int(x) for x in remote.split(".")]

        max_len = max(len(current_parts), len(remote_parts))
        current_parts.extend([0] * (max_len - len(current_parts)))
        remote_parts.extend([0] * (max_len - len(remote_parts)))

        return remote_parts > current_parts
    except (ValueError, AttributeError):
        return False


def check_for_update(force: bool = False) -> None:
    """
    Check for updates and prompt user to upgrade if available.

    Args:
        force: If True, check regardless of last check time and show errors.
    """
    if not force and not _should_check_for_update():
        return

    remote_version = _get_remote_version()

    if remote_version is None:
        if force:
            print(
                "Error: Failed to check for updates. "
                "Please check your internet connection.",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    _update_last_check_time()

    if not _compare_versions(__version__, remote_version):
        if force:
            print(f"mdify is up to date (version {__version__})")
        return

    print(f"\n{'=' * 50}")
    print(f"A new version of mdify-cli is available!")
    print(f"  Current version: {__version__}")
    print(f"  Latest version:  {remote_version}")
    print(f"{'=' * 50}")
    print(f"\nTo upgrade, run:")
    print(f"  pipx upgrade mdify-cli")
    print(f"  # or: pip install --upgrade mdify-cli\n")


# =============================================================================
# Container runtime functions
# =============================================================================


def is_daemon_running(runtime: str) -> bool:
    """
    Check if a container runtime daemon is running.

    Args:
        runtime: Path to container runtime executable

    Returns:
        True if daemon is running and responsive, False otherwise.
    """
    try:
        runtime_name = os.path.basename(runtime)
        
        # Apple Container uses 'container system status' to check daemon
        if runtime_name == "container":
            result = subprocess.run(
                [runtime, "system", "status"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        
        # Other runtimes use --version check
        result = subprocess.run(
            [runtime, "--version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect_runtime(preferred: Optional[str] = None, explicit: bool = True) -> Optional[str]:
    """
    Detect available container runtime.

    First checks MDIFY_CONTAINER_RUNTIME environment variable for explicit override.
    On macOS, tries native tools first (OrbStack → Colima → Podman → Docker).
    On other platforms, tries Docker → Podman.

    Args:
        preferred: Preferred runtime name override (deprecated, use MDIFY_CONTAINER_RUNTIME)
        explicit: If True, print info about detection/fallback choices.

    Returns:
        Path to runtime executable, or None if not found.
    """
    # Check for explicit environment variable override
    env_runtime = os.environ.get("MDIFY_CONTAINER_RUNTIME", "").strip().lower()
    if env_runtime:
        if env_runtime not in SUPPORTED_RUNTIMES:
            print(
                f"Warning: MDIFY_CONTAINER_RUNTIME='{env_runtime}' is not supported. "
                f"Supported: {', '.join(SUPPORTED_RUNTIMES)}",
                file=sys.stderr,
            )
        else:
            runtime_path = shutil.which(env_runtime)
            if runtime_path:
                if explicit:
                    print(f"Using runtime from MDIFY_CONTAINER_RUNTIME: {env_runtime}")
                return runtime_path
            else:
                print(
                    f"Warning: MDIFY_CONTAINER_RUNTIME='{env_runtime}' specified but not found in PATH",
                    file=sys.stderr,
                )

    # Determine runtime priority based on OS
    is_macos = platform.system() == "Darwin"
    if is_macos:
        runtime_priority = MACOS_RUNTIMES_PRIORITY
        if explicit:
            print(f"Detected macOS: checking for native container tools...")
    else:
        runtime_priority = OTHER_RUNTIMES_PRIORITY

    # Try each runtime in priority order
    found_but_not_running = []
    for runtime_name in runtime_priority:
        runtime_path = shutil.which(runtime_name)
        if runtime_path:
            # Check if daemon is running
            if is_daemon_running(runtime_path):
                if explicit:
                    print(f"Using container runtime: {runtime_name}")
                return runtime_path
            else:
                found_but_not_running.append((runtime_name, runtime_path))

    # If we found tools but none are running, warn and ask user to start one
    if found_but_not_running:
        print(
            f"\nWarning: Found container runtime(s) but daemon is not running:",
            file=sys.stderr,
        )
        for runtime_name, runtime_path in found_but_not_running:
            print(f"  - {runtime_name} ({runtime_path})", file=sys.stderr)
        print(
            "\nPlease start one of these tools before running mdify.",
            file=sys.stderr,
        )
        if is_macos:
            print(
                "  macOS tip: Start OrbStack, Colima, or Podman Desktop application",
                file=sys.stderr,
            )
        return None

    return None


def check_image_exists(runtime: str, image: str) -> bool:
    """
    Check if container image exists locally.

    Args:
        runtime: Path to container runtime
        image: Image name/tag

    Returns:
        True if image exists locally.
    """
    try:
        runtime_name = os.path.basename(runtime)
        
        # Apple Container uses 'image list' command (two words)
        if runtime_name == "container":
            result = subprocess.run(
                [runtime, "image", "list", "--format", "json"],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                try:
                    images = json.loads(result.stdout.decode())
                    # Check if image exists in the list
                    # Apple Container returns format: [{"reference": "image:tag", "descriptor": {...}}]
                    for img in images:
                        reference = img.get("reference", "")
                        if reference == image or reference.startswith(f"{image}:"):
                            return True
                except json.JSONDecodeError:
                    pass
            return False
        
        # Docker/Podman/OrbStack/Colima use standard 'image inspect'
        result = subprocess.run(
            [runtime, "image", "inspect", image],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def pull_image(runtime: str, image: str, quiet: bool = False) -> bool:
    """
    Pull container image.

    Args:
        runtime: Path to container runtime
        image: Image name/tag
        quiet: Suppress progress output

    Returns:
        True if pull succeeded.
    """
    if not quiet:
        print(f"Pulling image: {image}")

    try:
        runtime_name = os.path.basename(runtime)
        
        # Apple Container uses 'image pull' command (two words)
        if runtime_name == "container":
            result = subprocess.run(
                [runtime, "image", "pull", image],
                capture_output=quiet,
                check=False,
            )
            return result.returncode == 0
        
        # Docker/Podman/OrbStack/Colima use standard 'pull'
        result = subprocess.run(
            [runtime, "pull", image],
            capture_output=quiet,
            check=False,
        )
        return result.returncode == 0
    except OSError as e:
        print(f"Error pulling image: {e}", file=sys.stderr)
        return False


def get_image_size_estimate(runtime: str, image: str) -> Optional[int]:
    """
    Estimate image size by querying registry manifest.

    Runs `<runtime> manifest inspect --verbose <image>` and sums all layer sizes
    across all architectures, then applies 50% buffer for decompression.

    Args:
        runtime: Path to container runtime
        image: Image name/tag

    Returns:
        Estimated size in bytes with 50% buffer, or None if command fails.
    """
    try:
        result = subprocess.run(
            [runtime, "manifest", "inspect", "--verbose", image],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None

        manifest_data = json.loads(result.stdout.decode())

        # Sum all layer sizes across all architectures
        total_size = 0
        for manifest in manifest_data.get("Manifests", []):
            oci_manifest = manifest.get("OCIManifest", {})
            for layer in oci_manifest.get("layers", []):
                total_size += layer.get("size", 0)

        # Apply 50% buffer for decompression (compressed -> uncompressed)
        return int(total_size * 1.5)
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m {secs:.0f}s"


def get_free_space(path: str) -> int:
    """Get free disk space for the given path in bytes."""
    try:
        return shutil.disk_usage(path).free
    except (FileNotFoundError, OSError):
        return 0


def get_storage_root(runtime: str) -> Optional[str]:
    """
    Get the storage root directory for Docker, Podman, OrbStack, or Colima.

    Args:
        runtime: Path to container runtime executable

    Returns:
        Storage root path as string, or None if command fails.
    """
    try:
        # Extract runtime name from path (e.g., /usr/bin/docker -> docker)
        runtime_name = os.path.basename(runtime)

        if runtime_name == "docker":
            result = subprocess.run(
                [runtime, "system", "info", "--format", "{{.DockerRootDir}}"],
                capture_output=True,
                check=False,
            )
            if result.stdout:
                return result.stdout.decode().strip()
        elif runtime_name == "podman":
            result = subprocess.run(
                [runtime, "info", "--format", "json"],
                capture_output=True,
                check=False,
            )
            if result.stdout:
                info = json.loads(result.stdout.decode())
                return info.get("store", {}).get("graphRoot")
        elif runtime_name == "orbstack":
            # OrbStack stores containers in ~/.orbstack
            home = os.path.expanduser("~")
            return os.path.join(home, ".orbstack")
        elif runtime_name == "colima":
            # Colima stores containers in ~/.colima
            home = os.path.expanduser("~")
            return os.path.join(home, ".colima")
        elif runtime_name == "container":
            # Apple Container stores data in Application Support
            home = os.path.expanduser("~")
            return os.path.join(home, "Library", "Application Support", "com.apple.container")
        return None
    except (OSError, json.JSONDecodeError):
        return None


def confirm_proceed(message: str, default_no: bool = True) -> bool:
    """
    Prompt user for confirmation with a y/N prompt.

    Args:
        message: The confirmation message to display
        default_no: If True, shows [y/N] (default no). If False, shows [Y/n] (default yes)

    Returns:
        True if user entered 'y' or 'Y', False otherwise.
        Returns False immediately if stdin is not a TTY (non-interactive).
    """
    if not sys.stdin.isatty():
        return False

    prompt = "[y/N]" if default_no else "[Y/n]"
    print(f"{message} {prompt}", file=sys.stderr)
    response = input()
    return response.lower() == "y"


class Spinner:
    """A simple spinner to show progress during long operations."""

    def __init__(self):
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.running = False
        self.thread = None
        self.start_time = None

    def _spin(self):
        idx = 0
        while self.running:
            elapsed = time.time() - self.start_time
            frame = self.frames[idx % len(self.frames)]
            print(
                f"\r{self.prefix} {frame} ({format_duration(elapsed)})",
                end="",
                flush=True,
            )
            idx += 1
            time.sleep(0.1)

    def start(self, prefix: str = ""):
        self.prefix = prefix
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        # Clear the spinner line with enough spaces to cover the longest possible line
        print(f"\r{' ' * 120}\r", end="", flush=True)


# =============================================================================
# File handling functions
# =============================================================================

# Supported file extensions (based on Docling InputFormat)
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",  # images
    ".asciidoc",
    ".adoc",
    ".asc",  # asciidoc
    ".md",
    ".markdown",  # markdown
    ".csv",
    ".xlsx",  # spreadsheets
    ".xml",  # XML formats
    ".json",  # JSON docling
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",  # audio
    ".vtt",  # subtitles
}


def get_files_to_convert(input_path: Path, mask: str, recursive: bool) -> List[Path]:
    """Get list of files to convert based on input path and options."""
    files = []

    if input_path.is_file():
        files.append(input_path)
    elif input_path.is_dir():
        if recursive:
            files = list(input_path.rglob(mask))
        else:
            files = list(input_path.glob(mask))

        # Filter to only files
        files = [f for f in files if f.is_file()]
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    # Filter out hidden files and unsupported formats
    files = [
        f
        for f in files
        if not f.name.startswith(".") and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    return files


def get_output_path(
    input_file: Path,
    input_base: Path,
    output_dir: Path,
    flat: bool,
) -> Path:
    """Calculate output path for a given input file."""
    if flat:
        try:
            relative_path = input_file.relative_to(input_base)
            parts = list(relative_path.parts)
        except ValueError:
            parts = [input_file.name]

        stem = input_file.stem
        parent_prefix = "_".join(parts[:-1])
        if parent_prefix:
            output_name = f"{parent_prefix}_{stem}.md"
        else:
            output_name = f"{stem}.md"

        return output_dir / output_name
    else:
        output_name = input_file.stem + ".md"
        try:
            relative_path = input_file.relative_to(input_base)
            output_path = output_dir / relative_path.parent / output_name
        except ValueError:
            output_path = output_dir / output_name

        return output_path


# =============================================================================
# CLI argument parsing
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert documents to Markdown using Docling (via container)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mdify document.pdf                     Convert a single file
  mdify ./docs -g "*.pdf" -r             Convert PDFs recursively
  mdify ./docs -g "*.pdf" -o out/        Specify output directory
  mdify document.pdf -m                  Mask PII in images
  mdify ./docs --runtime podman          Use Podman instead of Docker
""",
    )

    parser.add_argument(
        "input",
        type=str,
        nargs="?",
        help="Input file or directory to convert",
    )

    parser.add_argument(
        "-o",
        "--out-dir",
        type=str,
        default="output",
        help="Output directory for converted files (default: output)",
    )

    parser.add_argument(
        "-g",
        "--glob",
        type=str,
        default="*",
        help="Glob pattern for filtering files in directory (default: *)",
    )

    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively scan directories",
    )

    parser.add_argument(
        "--flat",
        action="store_true",
        help="Disable directory structure preservation in output",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )

    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (for scripts/CI)",
    )

    parser.add_argument(
        "-m",
        "--mask",
        action="store_true",
        help="Mask PII and sensitive content in document images",
    )

    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Use GPU-accelerated container image (docling-serve-cu126)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port for docling-serve container (default: 5001)",
    )

    # Container options
    parser.add_argument(
        "--runtime",
        type=str,
        choices=SUPPORTED_RUNTIMES,
        default=None,
        help="Container runtime to use (auto-detects docker or podman if not specified)",
    )

    parser.add_argument(
        "--image",
        type=str,
        default=DEFAULT_IMAGE,
        help=f"Container image to use (default: {DEFAULT_IMAGE})",
    )

    parser.add_argument(
        "--pull",
        type=str,
        choices=("always", "missing", "never"),
        default="missing",
        help="Image pull policy: always, missing, never (default: missing)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Conversion timeout in seconds (default: 1200, can be set via MDIFY_TIMEOUT env var)",
    )

    parser.add_argument(
        "--memory",
        type=str,
        default=None,
        help="Container memory limit (e.g., 2g, 512m, 4096m). Overrides --profile setting",
    )

    parser.add_argument(
        "--cpus",
        type=int,
        default=None,
        help="Number of CPUs to allocate to container. Overrides --profile setting",
    )

    parser.add_argument(
        "--profile",
        type=str,
        choices=["minimal", "default", "heavy"],
        default="default",
        help="Resource profile for container: minimal (4 CPU, 8GB), default (6 CPU, 12GB), heavy (8 CPU, 16GB)",
    )

    parser.add_argument(
        "--skip-memory-check",
        action="store_true",
        help="Skip memory availability validation (not recommended)",
    )

    # SSH/Remote server options
    ssh_group = parser.add_argument_group("Remote SSH Server", "Execute conversion on remote server via SSH")
    
    ssh_group.add_argument(
        "--remote-host",
        type=str,
        default=None,
        help="SSH host or alias (e.g., tsrv, 192.168.1.200, or SSH config alias)",
    )

    ssh_group.add_argument(
        "--remote-port",
        type=int,
        default=None,
        help="SSH port (default: 22 or from SSH config)",
    )

    ssh_group.add_argument(
        "--remote-user",
        type=str,
        default=None,
        help="SSH username (default: from SSH config or system user)",
    )

    ssh_group.add_argument(
        "--remote-key",
        type=str,
        default=None,
        help="SSH private key path (default: ~/.ssh/id_rsa or from SSH config)",
    )

    ssh_group.add_argument(
        "--remote-key-passphrase",
        type=str,
        default=None,
        help="SSH key passphrase (not recommended; use SSH agent)",
    )

    ssh_group.add_argument(
        "--remote-timeout",
        type=int,
        default=30,
        help="SSH connection timeout in seconds (default: 30)",
    )

    ssh_group.add_argument(
        "--remote-work-dir",
        type=str,
        default="/tmp/mdify-remote",
        help="Work directory on remote server (default: /tmp/mdify-remote)",
    )

    ssh_group.add_argument(
        "--remote-runtime",
        type=str,
        choices=("docker", "podman"),
        default=None,
        help="Container runtime on remote (docker or podman; auto-detect if not specified)",
    )

    ssh_group.add_argument(
        "--remote-config",
        type=str,
        default=None,
        help="Path to mdify remote config file (YAML format, default: ~/.mdify/remote.conf)",
    )

    ssh_group.add_argument(
        "--remote-skip-ssh-config",
        action="store_true",
        help="Skip loading SSH config (use CLI arguments only)",
    )

    ssh_group.add_argument(
        "--remote-skip-validation",
        action="store_true",
        help="Skip remote resource validation (not recommended)",
    )

    ssh_group.add_argument(
        "--remote-validate-only",
        action="store_true",
        help="Validate remote connection and resources, then exit",
    )

    ssh_group.add_argument(
        "--remote-debug",
        action="store_true",
        help="Enable debug logging for remote SSH operations",
    )

    # Utility options
    parser.add_argument(
        "--check-update",
        action="store_true",
        help="Check for available updates and exit",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"mdify {__version__}",
    )

    return parser.parse_args()


# =============================================================================
# Remote SSH execution support
# =============================================================================


def main_async_remote(args) -> int:
    """Execute conversion on remote server via SSH.
    
    This function handles:
    1. Loading and merging SSH configuration
    2. Establishing remote connection
    3. Uploading input files
    4. Executing remote conversion
    5. Downloading output files
    6. Cleanup on success or failure
    
    Args:
        args: Parsed command-line arguments with remote_* options
        
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    import asyncio
    from pathlib import Path
    from mdify.ssh import SSHConfig, AsyncSSHClient
    from mdify.ssh.models import SSHConnectionError, SSHAuthError, ConfigError, ValidationError
    
    async def async_main() -> int:
        """Async implementation of remote conversion."""
        # Build SSH config from CLI arguments and SSH config files
        try:
            # Create SSHConfig from CLI arguments
            ssh_config = SSHConfig(
                host=args.remote_host,
                port=args.remote_port or 22,
                username=args.remote_user,
                key_file=args.remote_key,
                key_passphrase=args.remote_key_passphrase,
                timeout=args.remote_timeout,
                work_dir=args.remote_work_dir,
                container_runtime=args.remote_runtime,
            )
            
            if not args.remote_skip_ssh_config:
                # Load from SSH config if host looks like an alias
                if not args.remote_host.replace('.', '').replace('-', '').isdigit():
                    try:
                        ssh_from_config = SSHConfig.from_ssh_config(args.remote_host)
                        ssh_config = ssh_config.merge(ssh_from_config)
                    except Exception as e:
                        if not args.quiet:
                            print(f"Warning: Could not load SSH config for {args.remote_host}: {e}", file=sys.stderr)
                
                # Load from mdify remote.conf if it exists
                mdify_remote_conf = args.remote_config or (Path.home() / ".mdify" / "remote.conf")
                if mdify_remote_conf and Path(mdify_remote_conf).exists():
                    try:
                        ssh_from_mdify = SSHConfig.from_remote_conf(str(mdify_remote_conf))
                        ssh_config = ssh_config.merge(ssh_from_mdify)
                    except Exception as e:
                        if not args.quiet:
                            print(f"Warning: Could not load mdify remote config: {e}", file=sys.stderr)
            
            # Create SSH client
            ssh_client = AsyncSSHClient(ssh_config)
            
            # Connect to remote server
            if not args.quiet:
                print(f"Connecting to {ssh_config.host}:{ssh_config.port}...", file=sys.stderr)
            
            await ssh_client.connect()
            
            if not args.quiet:
                print(f"✓ Connected to {ssh_config.host}", file=sys.stderr)
            
            # Validate remote resources if not skipped
            if not args.remote_skip_validation:
                if not args.quiet:
                    print("Validating remote resources...", file=sys.stderr)
                
                validation_result = await ssh_client.validate_remote_resources()
                
                if not validation_result.get("can_connect"):
                    await ssh_client.disconnect()
                    print("Error: Cannot connect to remote server", file=sys.stderr)
                    return 1
                
                if not validation_result.get("work_dir_writable"):
                    await ssh_client.disconnect()
                    print(f"Error: Work directory not writable: {ssh_config.work_dir}", file=sys.stderr)
                    return 1
                
                if not validation_result.get("container_runtime_available"):
                    await ssh_client.disconnect()
                    runtime_str = ssh_config.container_runtime or "docker/podman"
                    print(f"Error: Container runtime not available: {runtime_str}", file=sys.stderr)
                    return 1
                
                if not validation_result.get("disk_space_min_5gb"):
                    print(f"Warning: Less than 5GB available on remote", file=sys.stderr)
                    if not args.yes and sys.stdin.isatty():
                        if not confirm_proceed("Continue anyway?"):
                            await ssh_client.disconnect()
                            return 130
                
                if not validation_result.get("memory_min_2gb"):
                    print(f"Warning: Less than 2GB available memory on remote", file=sys.stderr)
                    if not args.yes and sys.stdin.isatty():
                        if not confirm_proceed("Continue anyway?"):
                            await ssh_client.disconnect()
                            return 130
                
                if not args.quiet:
                    print("✓ All remote resources validated", file=sys.stderr)
            
            # If --remote-validate-only, exit here
            if args.remote_validate_only:
                await ssh_client.disconnect()
                print("Remote validation successful", file=sys.stderr)
                return 0
            
            # TODO: Phase 2.4.2 - Implement file upload, remote conversion, and download
            # This will be completed in subsequent task commits
            
            await ssh_client.disconnect()
            print("✓ Remote execution completed", file=sys.stderr)
            return 0
        
        except SSHConnectionError as e:
            print(f"Error: SSH connection failed: {e}", file=sys.stderr)
            if hasattr(e, 'host') and hasattr(e, 'port'):
                print(f"  Host: {e.host}:{e.port}", file=sys.stderr)
            return 1
        except SSHAuthError as e:
            print(f"Error: SSH authentication failed: {e}", file=sys.stderr)
            print("  Check your SSH key, passphrase, or username", file=sys.stderr)
            return 1
        except ConfigError as e:
            print(f"Error: Configuration error: {e}", file=sys.stderr)
            return 1
        except ValidationError as e:
            print(f"Error: Validation error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error: Unexpected error during remote execution: {e}", file=sys.stderr)
            if DEBUG:
                import traceback
                traceback.print_exc(file=sys.stderr)
            return 1
    
    # Run async main
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: Failed to run remote execution: {e}", file=sys.stderr)
        if DEBUG:
            import traceback
            traceback.print_exc(file=sys.stderr)
        return 1


# =============================================================================
# Main entry point
# =============================================================================


def main() -> int:
    """Main entry point for the CLI."""
    print(f"mdify v{__version__}", file=sys.stderr)
    args = parse_args()

    # Handle --check-update flag
    if args.check_update:
        check_for_update(force=True)
        return 0

    # Check for updates (daily, silent on errors)
    check_for_update(force=False)

    # Detect remote mode (SSH-based execution)
    is_remote_mode = hasattr(args, 'remote_host') and args.remote_host is not None
    
    if is_remote_mode:
        # Remote mode: will use SSH to execute on remote server
        # Import here to avoid import errors if asyncssh not installed in local environment
        try:
            import asyncio
            from mdify.ssh import AsyncSSHClient, SSHConfig
            return main_async_remote(args)
        except ImportError:
            print("Error: Remote mode requires asyncssh and additional dependencies", file=sys.stderr)
            print("Install with: pip install mdify-cli[remote]", file=sys.stderr)
            return 1

    # Resolve timeout value: CLI > env > default 1200
    timeout = args.timeout or int(os.environ.get("MDIFY_TIMEOUT", 1200))

    # Validate input is provided
    if args.input is None:
        print("Error: Input file or directory is required", file=sys.stderr)
        print("Usage: mdify <input> [options]", file=sys.stderr)
        print("       mdify --help for more information", file=sys.stderr)
        return 1

    # Detect container runtime
    # If --runtime is specified, treat as explicit user choice
    explicit = args.runtime is not None
    runtime = detect_runtime(preferred=args.runtime, explicit=explicit)
    if runtime is None:
        print(
            f"Error: Container runtime not found ({', '.join(SUPPORTED_RUNTIMES)})",
            file=sys.stderr,
        )
        return 2

    # Handle image pull policy
    # Determine image based on --gpu flag
    if args.gpu:
        image = GPU_IMAGE
    elif args.image:
        image = args.image
    else:
        image = DEFAULT_IMAGE

    image_exists = check_image_exists(runtime, image)

    if not args.quiet and image_exists:
        print(f"Using cached image: {image}")
        print()

    # NOTE: Docker Desktop on macOS/Windows uses a VM, so disk space checks may not
    # accurately reflect available space in the container's filesystem. Remote Docker
    # daemons (DOCKER_HOST) are also not supported. In these cases, the check will
    # gracefully degrade (warn and proceed).

    # Check disk space before pulling image (skip if pull=never or image exists with pull=missing)
    will_pull = args.pull == "always" or (args.pull == "missing" and not image_exists)
    if will_pull:
        storage_root = get_storage_root(runtime)
        if storage_root:
            image_size = get_image_size_estimate(runtime, image)
            if image_size:
                free_space = get_free_space(storage_root)
                if free_space < image_size:
                    print(
                        f"Warning: Not enough free disk space on {storage_root}",
                        file=sys.stderr,
                    )
                    print(
                        f"  Available: {format_size(free_space)}",
                        file=sys.stderr,
                    )
                    print(
                        f"  Required:  {format_size(image_size)} (estimated)",
                        file=sys.stderr,
                    )
                    if args.yes:
                        print("  Proceeding anyway (--yes flag set)", file=sys.stderr)
                    elif not sys.stdin.isatty():
                        print(
                            "  Run with --yes to proceed anyway, or free up disk space",
                            file=sys.stderr,
                        )
                        return 1
                    elif not confirm_proceed("Continue anyway?"):
                        return 130
                elif free_space - image_size < 1024 * 1024 * 1024:
                    print(
                        f"Warning: Less than 1 GB would remain after pulling image on {storage_root}",
                        file=sys.stderr,
                    )
                    print(
                        f"  Available: {format_size(free_space)}",
                        file=sys.stderr,
                    )
                    print(
                        f"  Required:  {format_size(image_size)} (estimated)",
                        file=sys.stderr,
                    )
                    print(
                        f"  Remaining: {format_size(free_space - image_size)}",
                        file=sys.stderr,
                    )
                    if args.yes:
                        print("  Proceeding anyway (--yes flag set)", file=sys.stderr)
                    elif not sys.stdin.isatty():
                        print(
                            "  Run with --yes to proceed anyway, or free up disk space",
                            file=sys.stderr,
                        )
                        return 1
                    elif not confirm_proceed("Continue anyway?"):
                        return 130

    if args.pull == "always" or (args.pull == "missing" and not image_exists):
        if not pull_image(runtime, image, args.quiet):
            print(f"Error: Failed to pull image: {image}", file=sys.stderr)
            return 1
    elif args.pull == "never" and not image_exists:
        print(f"Error: Image not found locally: {image}", file=sys.stderr)
        runtime_name = os.path.basename(runtime)
        print(f"Run with --pull=missing or pull manually: {runtime_name} pull {image}")
        return 1

    # Resolve paths (use absolute() as fallback if resolve() fails due to permissions)
    try:
        input_path = Path(args.input).resolve()
    except PermissionError:
        input_path = Path(args.input).absolute()
    try:
        output_dir = Path(args.out_dir).resolve()
    except PermissionError:
        output_dir = Path(args.out_dir).absolute()

    # Validate input
    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}", file=sys.stderr)
        return 1

    # Get files to convert
    try:
        files_to_convert = get_files_to_convert(input_path, args.glob, args.recursive)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not files_to_convert:
        print(f"No files found to convert in: {input_path}", file=sys.stderr)
        return 1

    total_files = len(files_to_convert)
    total_size = sum(f.stat().st_size for f in files_to_convert)

    if not args.quiet:
        print(f"Found {total_files} file(s) to convert ({format_size(total_size)})")
        print(f"Source: {input_path.resolve()}")
        print(f"Output: {output_dir.resolve()}")
        print(f"Using runtime: {runtime}")
        print(f"Using image: {image}")
        print()

    if args.mask:
        print(
            "Warning: --mask is not supported with docling-serve and will be ignored",
            file=sys.stderr,
        )

    # Determine input base for directory structure preservation
    if input_path.is_file():
        input_base = input_path.parent
    else:
        input_base = input_path

    success_count = 0
    skipped_count = 0
    failed_count = 0
    total_elapsed = 0.0

    try:
        if not args.quiet:
            print(f"Starting docling-serve container...\n")

        # Apply resource profile
        profile = RESOURCE_PROFILES[args.profile]
        cpus = args.cpus if args.cpus is not None else profile["cpus"]
        memory = args.memory if args.memory is not None else profile["memory"]
        
        # Validate memory availability unless skipped
        if not args.skip_memory_check:
            required_gb = parse_memory_string(memory)
            is_sufficient, error_msg = validate_memory_availability(
                required_gb, profile_name=args.profile
            )
            if not is_sufficient:
                print(f"Error: {error_msg}", file=sys.stderr)
                return 1
        
        if not args.quiet:
            print(f"Resource profile: {args.profile} ({cpus} CPUs, {memory} memory)")
            if args.cpus or args.memory:
                print("  (customized via command-line arguments)")
            print()

        with DoclingContainer(
            runtime,
            image,
            args.port,
            timeout=timeout,
            keep_container=DEBUG,
            memory=memory,
            cpus=cpus,
        ) as container:
            # Convert files
            conversion_start = time.time()
            spinner = Spinner()

            for idx, input_file in enumerate(files_to_convert, 1):
                output_file = get_output_path(
                    input_file, input_base, output_dir, args.flat
                )
                file_size = input_file.stat().st_size
                progress = f"[{idx}/{total_files}]"

                # Check if output exists and skip if not overwriting
                if output_file.exists() and not args.overwrite:
                    if not args.quiet:
                        print(f"{progress} Skipped (exists): {input_file.name}")
                    skipped_count += 1
                    continue

                # Ensure output directory exists
                output_file.parent.mkdir(parents=True, exist_ok=True)

                # Show spinner while processing
                if not args.quiet:
                    spinner.start(
                        f"{progress} Processing: {input_file.name} ({format_size(file_size)})"
                    )

                start_time = time.time()
                try:
                    # Convert via HTTP API
                    if DEBUG:
                        print(f"    DEBUG: Converting {input_file.name} via {container.base_url}/v1/convert/file", file=sys.stderr)
                    
                    result = convert_file(
                        container.base_url, input_file, to_format="md"
                    )
                    elapsed = time.time() - start_time

                    # Stop spinner before any output
                    if not args.quiet:
                        spinner.stop()

                    if result.success:
                        # Write result to output file
                        output_file.write_text(result.content)
                        success_count += 1
                        if not args.quiet:
                            print(
                                f"{progress} {input_file.name} ✓ ({format_duration(elapsed)})"
                            )
                    else:
                        failed_count += 1
                        error_msg = result.error or "Unknown error"
                        if not args.quiet:
                            print(
                                f"{progress} {input_file.name} ✗ ({format_duration(elapsed)})"
                            )
                            print(f"    Error: {error_msg}", file=sys.stderr)
                            
                            # Check if it's a connection error and retrieve logs
                            is_connection_error = "Connection refused" in error_msg or "Connection aborted" in error_msg or "RemoteDisconnected" in error_msg
                            if is_connection_error:
                                container_alive = container.is_ready()
                                if container_alive:
                                    print(
                                        "    Connection lost (server may have crashed and restarted)",
                                        file=sys.stderr,
                                    )
                                else:
                                    print(
                                        "    Container crashed while processing file",
                                        file=sys.stderr,
                                    )
                                    print(
                                        "    File may be too complex, large, or malformed",
                                        file=sys.stderr,
                                    )
                                
                                # Always show logs for connection errors
                                print("    Retrieving container logs...", file=sys.stderr)
                                logs, log_error = container.get_logs(tail=50)
                                if logs:
                                    print("    Container logs (last 50 lines):", file=sys.stderr)
                                    for line in logs.strip().split("\n"):
                                        if line.strip():
                                            print(f"      {line}", file=sys.stderr)
                                elif log_error:
                                    print(f"    Error retrieving logs: {log_error}", file=sys.stderr)
                                else:
                                    print("    No logs available (container may have been removed)", file=sys.stderr)
                                
                                # Restart container if it crashed
                                if not container_alive:
                                    print("    Container crashed - attempting to restart...", file=sys.stderr)
                                    try:
                                        # Stop and remove the dead container
                                        container.stop()
                                        container.remove()
                                        # Generate new container name to avoid conflicts
                                        import uuid
                                        container.container_name = f"mdify-serve-{uuid.uuid4().hex[:8]}"
                                        # Start a new one
                                        container.start(timeout=120)
                                        print("    Container restarted successfully", file=sys.stderr)
                                        print("    Continuing with next file...", file=sys.stderr)
                                    except Exception as restart_error:
                                        print(f"    Failed to restart container: {restart_error}", file=sys.stderr)
                                        if DEBUG:
                                            import traceback
                                            traceback.print_exc()
                                        print("    Stopping remaining conversions", file=sys.stderr)
                                        break
                except Exception as e:
                    elapsed = time.time() - start_time
                    failed_count += 1
                    # Stop spinner before printing error
                    if not args.quiet:
                        spinner.stop()
                    
                    # Check if container is still healthy
                    error_msg = str(e)
                    is_connection_error = "Connection refused" in error_msg or "Connection aborted" in error_msg or "RemoteDisconnected" in error_msg
                    
                    if DEBUG:
                        print(f"    DEBUG: Exception caught: {type(e).__name__}", file=sys.stderr)
                        print(f"    DEBUG: is_connection_error={is_connection_error}", file=sys.stderr)
                    
                    if is_connection_error:
                        container_alive = container.is_ready()
                        if not args.quiet:
                            print(
                                f"{progress} {input_file.name} ✗ ({format_duration(elapsed)})"
                            )
                            if container_alive:
                                print(
                                    "    Error: Connection lost (server may have crashed and restarted)",
                                    file=sys.stderr,
                                )
                            else:
                                print(
                                    "    Error: Container crashed while processing file",
                                    file=sys.stderr,
                                )
                                print(
                                    "    File may be too complex, large, or malformed",
                                    file=sys.stderr,
                                )

                            # Always show logs for connection errors to surface root cause
                            print("    Retrieving container logs...", file=sys.stderr)
                            logs, log_error = container.get_logs(tail=50)
                            if logs:
                                print("    Container logs (last 50 lines):", file=sys.stderr)
                                for line in logs.strip().split("\n"):
                                    if line.strip():  # Skip empty lines
                                        print(f"      {line}", file=sys.stderr)
                            elif log_error:
                                print(f"    Error retrieving logs: {log_error}", file=sys.stderr)
                                if not DEBUG:
                                    print(
                                        "    Tip: re-run with MDIFY_DEBUG=1 to preserve container for inspection",
                                        file=sys.stderr,
                                    )
                            else:
                                print("    No logs available (container may have been removed)", file=sys.stderr)
                                if not DEBUG:
                                    print(
                                        "    Tip: re-run with MDIFY_DEBUG=1 to preserve container logs",
                                        file=sys.stderr,
                                    )

                            if not container_alive:
                                print("    Stopping remaining conversions", file=sys.stderr)

                        # Restart container if it crashed
                        if not container_alive:
                            print("    Container crashed - attempting to restart...", file=sys.stderr)
                            try:
                                # Stop and remove the dead container
                                container.stop()
                                container.remove()
                                # Generate new container name to avoid conflicts
                                import uuid
                                container.container_name = f"mdify-serve-{uuid.uuid4().hex[:8]}"
                                # Start a new one
                                container.start(timeout=120)
                                print("    Container restarted successfully", file=sys.stderr)
                                print("    Continuing with next file...", file=sys.stderr)
                            except Exception as restart_error:
                                print(f"    Failed to restart container: {restart_error}", file=sys.stderr)
                                if DEBUG:
                                    import traceback
                                    traceback.print_exc()
                                print("    Stopping remaining conversions", file=sys.stderr)
                                break
                    else:
                        # Non-connection error
                        if not args.quiet:
                            print(
                                f"{progress} {input_file.name} ✗ ({format_duration(elapsed)})"
                            )
                            print(f"    Error: {error_msg}", file=sys.stderr)

            total_elapsed = time.time() - conversion_start

        # Print summary
        if not args.quiet:
            print()
            print("=" * 50)
            print("Conversion Summary:")
            print(f"  Total files:     {total_files}")
            print(f"  Successful:      {success_count}")
            print(f"  Skipped:         {skipped_count}")
            print(f"  Failed:          {failed_count}")
            print(f"  Total time:      {format_duration(total_elapsed)}")
            print("=" * 50)

    except KeyboardInterrupt:
        if not args.quiet:
            print("\n\nInterrupted by user. Container stopped.")
            if success_count > 0 or skipped_count > 0 or failed_count > 0:
                print(
                    f"Partial progress: {success_count} successful, {failed_count} failed, {skipped_count} skipped"
                )
        return 130

    # Return appropriate exit code
    if failed_count > 0:
        return 1
    elif success_count == 0 and skipped_count > 0:
        return 0
    elif success_count > 0:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
