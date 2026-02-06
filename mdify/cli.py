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
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from . import __version__
from mdify.container import DoclingContainer, cleanup_managed_containers, CleanupSummary
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

    from mdify.formatting import Colorizer
    
    if not _compare_versions(__version__, remote_version):
        if force:
            color = Colorizer(sys.stdout)
            print(color.success(f"✓ mdify is up to date (v{__version__})"))
        return

    color = Colorizer(sys.stdout)
    print(f"\n{color.bright_yellow('=' * 60)}")
    print(color.bold_yellow("🎉 A new version of mdify-cli is available!"))
    print(f"{color.dim_white('  Current:')} {__version__} → {color.bright_green(remote_version)}")
    print(f"{color.bright_yellow('=' * 60)}")
    print(f"\n{color.cyan('To upgrade, run:')}")
    print(f"  {color.bold('pipx upgrade mdify-cli')}")
    print(f"  {color.dim_white('# or: pip install --upgrade mdify-cli')}\n")


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


def _print_cleanup_summary(summary: CleanupSummary, color, quiet: bool) -> None:
    """Print cleanup summary and failures."""
    if quiet:
        return

    target_label = "Local" if summary.target == "local" else "Remote"
    print(color.cyan(f"{target_label} cleanup summary:"), file=sys.stderr)
    print(
        f"  {color.green('Stopped:')} {summary.stopped_count}  {color.green('Removed:')} {summary.removed_count}",
        file=sys.stderr,
    )
    if summary.failures:
        print(color.yellow(f"  Failures: {len(summary.failures)}"), file=sys.stderr)
        for failure in summary.failures:
            print(
                color.yellow(
                    f"    - {failure.container_name} ({failure.action}): {failure.reason}"
                ),
                file=sys.stderr,
            )


def _handle_cleanup_failure(summary: CleanupSummary, args, color) -> bool:
    """Handle cleanup failures with optional confirmation.

    Returns True if processing should proceed, False otherwise.
    """
    if not summary.failures:
        return True

    if args.yes:
        summary.proceeded_after_failure = True
        return True

    if confirm_proceed("Cleanup failed. Continue anyway?"):
        summary.proceeded_after_failure = True
        return True

    print(color.error("✗ Cleanup failed and was not confirmed. Aborting."), file=sys.stderr)
    return False


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

# Supported file extensions for conversion (based on official Docling InputFormat)
# See: https://docs.docling.ai/latest/features/document_conversion_guide/
SUPPORTED_EXTENSIONS = {
    # Document formats
    ".pdf",  # PDF
    ".docx",  # Microsoft Word (Office Open XML)
    ".xlsx",  # Microsoft Excel (Office Open XML)
    ".pptx",  # Microsoft PowerPoint (Office Open XML)
    ".html",  # HTML
    ".htm",   # HTML variant
    ".xhtml", # XHTML
    ".asciidoc",
    ".adoc",
    ".asc",  # AsciiDoc formats
    # Data formats
    ".csv",  # Comma-separated values
    # Image formats
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",  # Images
    # Text/Subtitle formats
    ".vtt",  # WebVTT (Web Video Text Tracks)
}

# File extensions that should be skipped (not converted to markdown)
# These formats are already in markdown or similar text format
SKIPPED_EXTENSIONS = {
    ".md",
    ".markdown",  # Already markdown - no need to convert
    ".json",
    ".xml",
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

    # Filter out hidden files, unsupported formats, and non-convertible formats
    files = [
        f
        for f in files
        if not f.name.startswith(".")
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
        and f.suffix.lower() not in SKIPPED_EXTENSIONS
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
        help="Conversion timeout in seconds (default: 1200s for local, 3600s for remote with large PDFs, can be set via MDIFY_TIMEOUT env var)",
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
        from mdify.formatting import Colorizer
        from mdify.docling_client import _is_error_response, _extract_content

        color = Colorizer(sys.stderr)
        
        # Resolve timeout value: CLI > env > default 1200
        timeout = args.timeout if args.timeout is not None else int(os.environ.get("MDIFY_TIMEOUT", 1200))
        
        # For remote operations, extend timeout significantly for large PDF processing
        # Remote conversions include network latency, file upload/download, and OCR processing
        remote_conversion_timeout = max(timeout or 1200, 3600)  # At least 1 hour for remote conversion
        
        # Build SSH config from CLI arguments and SSH config files
        try:
            # Build config with proper precedence (lowest to highest):
            # SSH config -> mdify remote.conf -> CLI args
            ssh_config = None
            
            if not args.remote_skip_ssh_config:
                # Load from SSH config if host looks like an alias
                if not args.remote_host.replace('.', '').replace('-', '').isdigit():
                    try:
                        ssh_config = SSHConfig.from_ssh_config(args.remote_host)
                    except Exception as e:
                        if not args.quiet:
                            print(f"Warning: Could not load SSH config for {args.remote_host}: {e}", file=sys.stderr)
                
                # Load from mdify remote.conf if it exists
                mdify_remote_conf = args.remote_config or (Path.home() / ".mdify" / "remote.conf")
                if mdify_remote_conf and Path(mdify_remote_conf).exists():
                    try:
                        ssh_from_mdify = SSHConfig.from_remote_conf(str(mdify_remote_conf))
                        if ssh_config:
                            ssh_config = ssh_config.merge(ssh_from_mdify)
                        else:
                            ssh_config = ssh_from_mdify
                    except Exception as e:
                        if not args.quiet:
                            print(f"Warning: Could not load mdify remote config: {e}", file=sys.stderr)
            
            # Start with minimal defaults if no config loaded
            if ssh_config is None:
                ssh_config = SSHConfig(host=args.remote_host, port=22, username="")
            
            # Apply CLI arguments with highest precedence (only pass non-None values)
            cli_config_kwargs = {
                "host": args.remote_host,
                "source": "cli",
            }
            if args.remote_port is not None:
                cli_config_kwargs["port"] = args.remote_port
            if args.remote_user:
                cli_config_kwargs["username"] = args.remote_user
            if args.remote_key:
                cli_config_kwargs["key_file"] = args.remote_key
            if args.remote_key_passphrase:
                cli_config_kwargs["key_passphrase"] = args.remote_key_passphrase
            if args.remote_timeout is not None:
                cli_config_kwargs["timeout"] = args.remote_timeout
            if args.remote_work_dir:
                cli_config_kwargs["work_dir"] = args.remote_work_dir
            if args.remote_runtime:
                cli_config_kwargs["container_runtime"] = args.remote_runtime
            
            cli_config = SSHConfig(**cli_config_kwargs)
            ssh_config = ssh_config.merge(cli_config)
            
            # Create SSH client
            ssh_client = AsyncSSHClient(ssh_config)
            
            # Connect to remote server
            if not args.quiet:
                print(color.bright_cyan(f"🔗 Connecting to {color.bold(ssh_config.host)}:{ssh_config.port}..."), file=sys.stderr)
            
            await ssh_client.connect()
            
            if not args.quiet:
                print(color.success(f"✓ Connected to {ssh_config.host}"), file=sys.stderr)
            
            # Validate remote resources if not skipped
            if not args.remote_skip_validation:
                if not args.quiet:
                    print(color.cyan("🔍 Validating remote resources..."), file=sys.stderr)
                
                validation_result = await ssh_client.validate_remote_resources()
                
                if not validation_result.get("can_connect"):
                    await ssh_client.disconnect()
                    print(color.error("✗ Cannot connect to remote server"), file=sys.stderr)
                    return 1
                
                if not validation_result.get("work_dir_writable"):
                    await ssh_client.disconnect()
                    print(color.error(f"✗ Work directory not writable: {ssh_config.work_dir}"), file=sys.stderr)
                    return 1
                
                if not validation_result.get("container_runtime_available"):
                    await ssh_client.disconnect()
                    runtime_str = ssh_config.container_runtime or "docker/podman"
                    print(color.error(f"✗ Container runtime not available: {runtime_str}"), file=sys.stderr)
                    return 1
                
                if not validation_result.get("disk_space_min_5gb"):
                    print(color.warning(f"⚠ Less than 5GB available on remote"), file=sys.stderr)
                    if not args.yes and sys.stdin.isatty():
                        if not confirm_proceed("Continue anyway?"):
                            await ssh_client.disconnect()
                            return 130
                
                if not validation_result.get("memory_min_2gb"):
                    print(color.warning(f"⚠ Less than 2GB available memory on remote"), file=sys.stderr)
                    if not args.yes and sys.stdin.isatty():
                        if not confirm_proceed("Continue anyway?"):
                            await ssh_client.disconnect()
                            return 130
                
                if not args.quiet:
                    print(color.success("✓ All remote resources validated"), file=sys.stderr)
            
            # If --remote-validate-only, exit here
            if args.remote_validate_only:
                await ssh_client.disconnect()
                print(color.success("✓ Remote validation successful"), file=sys.stderr)
                return 0
            
            # Phase 2.4.2: File upload, remote conversion, and download
            
            # Build file list
            input_path = Path(args.input)
            if not input_path.exists():
                await ssh_client.disconnect()
                print(f"{color.error('✗ Error:')} Input file or directory not found: {args.input}", file=sys.stderr)
                return 1
            
            # Store resolved path as base for relative path calculations
            input_base = input_path.resolve()
            files_to_convert = get_files_to_convert(input_base, args.glob, args.recursive)
            
            if not files_to_convert:
                await ssh_client.disconnect()
                print(f"{color.error('✗ Error:')} No supported files found in {args.input}", file=sys.stderr)
                print(f"  {color.dim_white(f'Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}')} ", file=sys.stderr)
                return 1
            
            if not args.quiet:
                print(color.cyan(f"Found {len(files_to_convert)} file(s) to convert"), file=sys.stderr)
                print(color.cyan(f"Conversion timeout: {remote_conversion_timeout}s (for large PDFs with OCR)"), file=sys.stderr)
            
            # Import remote container and transfer manager
            from mdify.ssh.transfer import FileTransferManager
            from mdify.ssh.remote_container import RemoteContainer, cleanup_managed_containers as remote_cleanup
            
            # Determine container runtime and image
            runtime = ssh_config.container_runtime
            if not runtime:
                runtime = await ssh_client.check_container_runtime()
                if not runtime:
                    await ssh_client.disconnect()
                    print("Error: No container runtime found on remote (docker/podman)", file=sys.stderr)
                    return 1
            
            if args.gpu:
                image = GPU_IMAGE
            elif args.image:
                image = args.image
            else:
                image = DEFAULT_IMAGE
            
            # Create remote container
            remote_container = RemoteContainer(
                ssh_client=ssh_client,
                image=image,
                port=args.port,
                runtime=runtime,
                name=f"mdify-remote-{int(time.time())}",
                timeout=timeout,
            )
            
            # Create file transfer manager
            transfer_manager = FileTransferManager(ssh_client)
            
            # Create remote work directory
            work_dir = ssh_config.work_dir or "/tmp/mdify-remote"
            stdout, stderr, code = await ssh_client.run_command(f"mkdir -p {work_dir}")
            if code != 0:
                await ssh_client.disconnect()
                print(f"Error: Failed to create remote work directory: {work_dir}", file=sys.stderr)
                return 1

            cleanup_summary = await remote_cleanup(ssh_client, runtime)
            _print_cleanup_summary(cleanup_summary, color, args.quiet)
            if not _handle_cleanup_failure(cleanup_summary, args, color):
                await ssh_client.disconnect()
                return 130
            
            # Start remote container
            if not args.quiet:
                print(color.cyan(f"\nStarting remote container ({image})..."), file=sys.stderr)
            
            try:
                await remote_container.start()
                if not args.quiet:
                    print(color.green(f"✓ Container started: {remote_container.state.container_name}"), file=sys.stderr)
            except Exception as e:
                await ssh_client.disconnect()
                print(f"Error: Failed to start remote container: {e}", file=sys.stderr)
                return 1
            
            # Process files
            successful = 0
            failed = 0
            
            def is_connection_error(exc: Exception) -> bool:
                if isinstance(exc, SSHConnectionError):
                    return True
                msg = str(exc).lower()
                # Errno 32 = Broken pipe, Errno 54 = Connection reset by peer
                return any(x in msg for x in ["broken pipe", "connection closed", "connection reset", "errno 32", "errno 54", "ssh connection"])
            
            try:
                for idx, input_file in enumerate(files_to_convert, 1):
                    if not args.quiet:
                        print(
                            f"\n{color.cyan(f'[{idx}/{len(files_to_convert)}] Processing:')} {input_file.name}",
                            file=sys.stderr,
                        )
                    
                    attempt = 0
                    while attempt <= 1:  # Max 2 attempts (0 and 1)
                        try:
                            # Upload file
                            remote_file_path = f"{work_dir}/{input_file.name}"
                            
                            if not args.quiet:
                                print(f"  {color.cyan('Uploading to')} {remote_file_path}...", file=sys.stderr)
                            
                            await transfer_manager.upload_file(
                                local_path=str(input_file),
                                remote_path=remote_file_path,
                                overwrite=True,
                                compress=False,
                            )
                            
                            if not args.quiet:
                                print(f"  {color.green('✓ Upload complete')}", file=sys.stderr)
                            
                            # Convert via remote container
                            if not args.quiet:
                                print(f"  {color.cyan('Converting via remote container')}...", file=sys.stderr)
                            
                            # Determine output path
                            output_dir = Path(args.out_dir)
                            output_file = get_output_path(input_file, input_base, output_dir, args.flat)
                            
                            # Ensure output directory exists
                            output_file.parent.mkdir(parents=True, exist_ok=True)
                            
                            # Check if output exists and skip if not overwrite
                            if output_file.exists() and not args.overwrite:
                                if not args.quiet:
                                    print(
                                        f"  {color.yellow('⊘ Skipped:')} {output_file} already exists (use --overwrite to replace)",
                                        file=sys.stderr,
                                    )
                                break
                            
                            # Convert using remote container's HTTP API
                            # The docling-serve API expects:
                            # - Endpoint: /v1/convert/file
                            # - Method: POST with multipart/form-data
                            # - File field: "files" (note the plural)
                            # - Additional fields: to_formats=md, do_ocr=true
                            remote_output_path = f"{work_dir}/{input_file.stem}.md"
                            
                            # Build conversion command on remote - use -F for multipart form data
                            # Important: use generous timeouts since large PDFs with OCR take time
                            # --connect-timeout: max time to establish connection (60s)
                            # --max-time: max total operation time (extended timeout)
                            convert_cmd = (
                                f"curl -X POST "
                                f"--connect-timeout 60 "
                                f"--max-time {remote_conversion_timeout} "
                                f"-F files=@{shlex.quote(remote_file_path)} "
                                f"-F to_formats=md "
                                f"-F do_ocr=true "
                            )
                            if args.mask:
                                convert_cmd += f"-F mask=true "
                            convert_cmd += f"http://localhost:{args.port}/v1/convert/file"
                            
                            # Retry conversion command with exponential backoff
                            conversion_attempt = 0
                            conversion_success = False
                            conversion_output = None
                            while conversion_attempt < 3 and not conversion_success:
                                conversion_attempt += 1
                                try:
                                    if conversion_attempt > 1 and not args.quiet:
                                        # Exponential backoff: 2s, 4s
                                        backoff_delay = 2 ** (conversion_attempt - 1)
                                        print(f"  ↻ Conversion retry {conversion_attempt - 1} (waiting {backoff_delay}s for server recovery)...", file=sys.stderr)
                                        await asyncio.sleep(backoff_delay)
                                    
                                    conversion_output, stderr_output, conv_code = await ssh_client.run_command(convert_cmd, timeout=remote_conversion_timeout)
                                    
                                    if conv_code == 0:
                                        conversion_success = True
                                        break
                                    else:
                                        # Non-zero exit code - fail without retry for non-connection errors
                                        if not args.quiet:
                                            print(f"  ✗ curl exited with code {conv_code}", file=sys.stderr)
                                            if conversion_output:
                                                print(f"  Output: {conversion_output[:500]}", file=sys.stderr)
                                            if stderr_output:
                                                print(f"  Error: {stderr_output[:500]}", file=sys.stderr)
                                        break
                                except Exception as conv_exc:
                                    is_conn_err = is_connection_error(conv_exc)
                                    if is_conn_err and conversion_attempt < 3:
                                        if not args.quiet:
                                            # Exponential backoff: 5s, 10s
                                            backoff_delay = 5 * conversion_attempt
                                            print(f"  ↻ Connection reset during conversion. Reconnecting in {backoff_delay}s...", file=sys.stderr)
                                        
                                        await asyncio.sleep(backoff_delay)
                                        
                                        try:
                                            await ssh_client.disconnect()
                                        except Exception:
                                            # Best-effort disconnect; ignore errors (e.g., already closed) before reconnecting
                                            pass
                                        
                                        # Reconnect with retry
                                        try:
                                            await ssh_client.connect()
                                        except Exception:
                                            if not args.quiet:
                                                print(f"  ⚠ Reconnection failed: retrying...", file=sys.stderr)
                                            continue
                                    else:
                                        # Either not a connection error, or we've exhausted retries
                                        if conversion_attempt >= 3 and is_conn_err:
                                            if not args.quiet:
                                                print(f"  ↻ Connection error on final retry attempt", file=sys.stderr)
                                        break
                            
                            if not conversion_success:
                                print(f"  {color.error('✗ Failed:')} Conversion failed after {conversion_attempt} attempt(s)", file=sys.stderr)
                                failed += 1
                                break
                            
                            # Parse JSON response to extract markdown content
                            try:
                                response_data = json.loads(conversion_output)
                                color_err = Colorizer(sys.stderr)
                                
                                # Debug: Print JSON schema structure
                                if DEBUG:
                                    def get_schema(obj, depth=0, max_depth=3):
                                        """Get JSON schema structure."""
                                        if depth > max_depth:
                                            return "..."
                                        if isinstance(obj, dict):
                                            return "{" + ", ".join(f"{k}: {get_schema(v, depth+1)}" for k, v in list(obj.items())[:5]) + ("..." if len(obj) > 5 else "") + "}"
                                        elif isinstance(obj, list):
                                            return "[" + (get_schema(obj[0], depth+1) if obj else "") + ("..." if len(obj) > 1 else "") + "]"
                                        elif isinstance(obj, str):
                                            return f"str({len(obj)} chars)"
                                        else:
                                            return type(obj).__name__
                                    schema = get_schema(response_data)
                                    print(f"  Response schema: {schema}", file=sys.stderr)
                                
                                # Check if response is an error response
                                if _is_error_response(response_data):
                                    error_detail = response_data.get("detail", response_data.get("error", str(response_data)))
                                    print(f"  {color_err.error('✗ Failed:')} {error_detail}", file=sys.stderr)
                                    if "DOCLING_SERVE_MAX_SYNC_WAIT" in str(error_detail):
                                        timeout_val = args.timeout or 3600
                                        print(f"  {color_err.info('ℹ Tip:')} Increase timeout with --timeout (current: {timeout_val}s)", file=sys.stderr)
                                    failed += 1
                                    break
                                
                                # Extract content from response using proper extraction function
                                markdown_content = _extract_content(response_data)
                                
                                # Validate content exists and is not empty/too short
                                if not markdown_content or len(markdown_content.strip()) < 50:
                                    print(f"  {color_err.error('✗ Failed:')} Empty or invalid conversion result", file=sys.stderr)
                                    if args.timeout and args.timeout < 300:
                                        print(
                                            f"  {color_err.info('ℹ Tip:')} Timeout is only {args.timeout}s. Consider increasing with --timeout (default: 3600s for remote)",
                                            file=sys.stderr,
                                        )
                                    failed += 1
                                    break
                                
                                # Write markdown content to local temp file first, then upload via SFTP
                                # (Piping large content through SSH here-documents can crash the connection)
                                content_size_kb = len(markdown_content) / 1024
                                if not args.quiet:
                                    print(f"  {color.cyan('Writing')} {content_size_kb:.1f}KB markdown via SFTP...", file=sys.stderr)
                                
                                temp_path = None
                                try:
                                    # Write to temporary local file
                                    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
                                        temp_file.write(markdown_content)
                                        temp_path = temp_file.name
                                    
                                    # Upload via SFTP (more reliable for large files)
                                    await transfer_manager.upload_file(
                                        local_path=temp_path,
                                        remote_path=remote_output_path,
                                        overwrite=True,
                                        compress=False,
                                    )
                                    
                                    if not args.quiet:
                                        print(f"  {color.green('✓')} Markdown written", file=sys.stderr)
                                except Exception as write_exc:
                                    if not args.quiet:
                                        print(f"  ✗ Failed to write markdown: {write_exc}", file=sys.stderr)
                                    failed += 1
                                    break
                                finally:
                                    # Cleanup temp file
                                    if temp_path:
                                        try:
                                            os.unlink(temp_path)
                                        except Exception as cleanup_exc:
                                            if DEBUG:
                                                print(f"  ! Failed to remove temporary file {temp_path}: {cleanup_exc}", file=sys.stderr)
                                
                            except (json.JSONDecodeError, KeyError, IndexError):
                                print(f"  ✗ Failed to parse conversion response", file=sys.stderr)
                                if DEBUG and conversion_output:
                                    # Only print a snippet of the response for debugging
                                    response_snippet = conversion_output[:300] + ("..." if len(conversion_output) > 300 else "")
                                    print(f"  Response snippet: {response_snippet}", file=sys.stderr)
                                failed += 1
                                break
                            
                            if not args.quiet:
                                print(f"  ✓ Conversion complete", file=sys.stderr)
                            
                            # Download result
                            if not args.quiet:
                                print(color.cyan(f"  Downloading result to {output_file}..."), file=sys.stderr)
                            
                            await transfer_manager.download_file(
                                remote_path=remote_output_path,
                                local_path=str(output_file),
                                overwrite=True,
                            )
                            
                            if not args.quiet:
                                print(color.green(f"  ✓ Download complete: {output_file}"), file=sys.stderr)
                            
                            successful += 1
                            
                            # Cleanup remote files
                            await ssh_client.run_command(f"rm -f {shlex.quote(remote_file_path)} {shlex.quote(remote_output_path)}")
                            
                            break
                        except Exception as e:
                            if is_connection_error(e) and attempt == 0:
                                attempt += 1
                                if not args.quiet:
                                    print(color.yellow("  ↻ Connection lost. Reconnecting..."), file=sys.stderr)
                                try:
                                    await ssh_client.disconnect()
                                except Exception:
                                    # Best-effort disconnect; ignore errors since we'll immediately reconnect.
                                    pass
                                await ssh_client.connect()
                                continue
                            
                            print(f"  {color.error('✗ Failed:')} {str(e)}", file=sys.stderr)
                            if DEBUG:
                                import traceback
                                traceback.print_exc(file=sys.stderr)
                            failed += 1
                            break
            
            finally:
                # Stop and remove container
                if not args.quiet:
                    print(color.cyan(f"\nStopping remote container..."), file=sys.stderr)
                
                try:
                    await remote_container.stop(force=False)
                    if not args.quiet:
                        print(color.green(f"✓ Container stopped"), file=sys.stderr)
                except Exception as e:
                    if not args.quiet:
                        print(color.yellow(f"Warning: Failed to stop container: {e}"), file=sys.stderr)
                
                # Cleanup remote work directory
                try:
                    await ssh_client.run_command(f"rm -rf {shlex.quote(work_dir)}")
                    if not args.quiet:
                        print(color.green(f"✓ Cleaned up remote directory"), file=sys.stderr)
                except Exception as e:
                    if not args.quiet:
                        print(f"Warning: Failed to cleanup remote directory: {e}", file=sys.stderr)
                
                # Disconnect
                await ssh_client.disconnect()
            
            # Print summary
            print(color.cyan(f"\n{'='*60}"), file=sys.stderr)
            print(color.bold_cyan("📊 Remote Conversion Summary"), file=sys.stderr)
            print(color.cyan(f"{'='*60}"), file=sys.stderr)
            
            # Format summary with emojis and colors
            total = len(files_to_convert)
            success_pct = f" ({successful}/{total})" if total > 0 else ""
            failed_pct = f" ({failed}/{total})" if total > 0 else ""
            skipped_pct = f" ({total - successful - failed}/{total})" if total > 0 else ""
            
            print(f"  {color.green('✓ Successful:')} {color.bold_green(str(successful))}{success_pct}", file=sys.stderr)
            if failed > 0:
                print(f"  {color.red('✗ Failed:')} {color.bold_red(str(failed))}{failed_pct}", file=sys.stderr)
            if (total - successful - failed) > 0:
                print(f"  {color.yellow('⊘ Skipped:')} {color.bold_yellow(str(total - successful - failed))}{skipped_pct}", file=sys.stderr)
            print(f"  {color.cyan('Total:')} {color.bold(str(total))}", file=sys.stderr)
            print(color.cyan(f"{'='*60}"), file=sys.stderr)
            
            return 0 if failed == 0 else 1
        
        except SSHAuthError as e:
            print(color.yellow(f"Error: SSH authentication failed: {e}"), file=sys.stderr)
            print("  Check your SSH key, passphrase, or username", file=sys.stderr)
            return 1
        except SSHConnectionError as e:
            print(color.yellow(f"Error: SSH connection failed: {e}"), file=sys.stderr)
            if hasattr(e, 'host') and hasattr(e, 'port'):
                print(f"  Host: {e.host}:{e.port}", file=sys.stderr)
            return 1
        except ConfigError as e:
            print(f"Error: Configuration error: {e}", file=sys.stderr)
            return 1
        except ValidationError as e:
            print(f"Error: Validation error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error: Unexpected error during remote execution: {e}", file=sys.stderr)
            # Always print traceback for unexpected errors to help with debugging
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
    from mdify.formatting import Colorizer
    
    color_stderr = Colorizer(sys.stderr)
    color_stdout = Colorizer(sys.stdout)
    
    print(color_stderr.bold_cyan(f"📄 mdify v{__version__}"), file=sys.stderr)
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
        print(f"{color_stderr.error('✗ Error:')} Input path does not exist: {input_path}", file=sys.stderr)
        return 1

    # Get files to convert
    try:
        files_to_convert = get_files_to_convert(input_path, args.glob, args.recursive)
    except Exception as e:
        print(f"{color_stderr.error('✗ Error:')} {e}", file=sys.stderr)
        return 1

    if not files_to_convert:
        print(f"{color_stderr.warning('⚠ Warning:')} No files found to convert in: {input_path}", file=sys.stderr)
        return 1

    total_files = len(files_to_convert)
    total_size = sum(f.stat().st_size for f in files_to_convert)

    if not args.quiet:
        print(f"{color_stdout.bright_cyan('📦 Found')} {color_stdout.bold(str(total_files))} {color_stdout.bright_cyan('file(s)')} {color_stdout.dim_white(f'({format_size(total_size)})')}")
        print(f"{color_stdout.cyan('📁 Source:')} {color_stdout.bright_white(str(input_path.resolve()))}")
        print(f"{color_stdout.cyan('💾 Output:')} {color_stdout.bright_white(str(output_dir.resolve()))}")
        print(f"{color_stdout.cyan('🐳 Runtime:')} {color_stdout.bright_white(runtime)}")
        print(f"{color_stdout.cyan('🖼️  Image:')} {color_stdout.dim_white(image)}")
        print()

    if args.mask:
        print(
            color_stderr.warning("⚠ --mask is not supported with docling-serve and will be ignored"),
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

        cleanup_summary = cleanup_managed_containers(runtime)
        _print_cleanup_summary(cleanup_summary, color_stderr, args.quiet)
        if not _handle_cleanup_failure(cleanup_summary, args, color_stderr):
            return 130

        if not args.quiet:
            print(f"{color_stdout.bright_cyan('▶️  Starting')} {color_stdout.bright_white('docling-serve')} {color_stdout.bright_cyan('container')}...\n")

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
                        # Validate content is not empty and not an error response
                        content_length = len(result.content.strip()) if result.content else 0
                        if content_length < 50:
                            # Too short - likely an error or empty document
                            failed_count += 1
                            if not args.quiet:
                                print(
                                    f"{progress} {input_file.name} ✗ ({format_duration(elapsed)})"
                                )
                                error_msg = "Empty or invalid conversion result"
                                if result.content:
                                    error_msg += f" ({len(result.content)} bytes)"
                                print(f"    Error: {error_msg}", file=sys.stderr)
                                if args.timeout and args.timeout < 300:
                                    color_out = Colorizer(sys.stderr)
                                    print(
                                        f"    {color_out.info('ℹ Tip:')} Timeout is only {args.timeout}s. Consider increasing with --timeout (default: 1200s)",
                                        file=sys.stderr,
                                    )
                        else:
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
            print(color_stdout.cyan("=" * 60))
            print(color_stdout.bold_cyan("📊 Local Conversion Summary"))
            print(color_stdout.cyan("=" * 60))
            print(f"  {color_stdout.cyan('Total files:')} {color_stdout.bold(str(total_files))}")
            if success_count > 0:
                print(f"  {color_stdout.green('✓ Successful:')} {color_stdout.bold_green(str(success_count))}")
            if skipped_count > 0:
                print(f"  {color_stdout.yellow('⊘ Skipped:')} {color_stdout.bold_yellow(str(skipped_count))}")
            if failed_count > 0:
                print(f"  {color_stdout.red('✗ Failed:')} {color_stdout.bold_red(str(failed_count))}")
            print(f"  {color_stdout.cyan('Total time:')} {color_stdout.bright_cyan(format_duration(total_elapsed))}")
            print(color_stdout.cyan("=" * 60))

    except KeyboardInterrupt:
        if not args.quiet:
            print(f"\n\n{color_stdout.warning('⚠ Interrupted by user. Container stopped.')}")
            if success_count > 0 or skipped_count > 0 or failed_count > 0:
                print(
                    f"{color_stdout.dim_white('Partial progress:')} {color_stdout.green(str(success_count))} successful, {color_stdout.red(str(failed_count))} failed, {color_stdout.yellow(str(skipped_count))} skipped"
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
