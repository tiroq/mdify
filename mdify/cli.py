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
SUPPORTED_RUNTIMES = ("docker", "podman")


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


def detect_runtime(preferred: str, explicit: bool = True) -> Optional[str]:
    """
    Detect available container runtime.

    Args:
        preferred: Preferred runtime ('docker' or 'podman')
        explicit: If True, warn when falling back to alternative.
                  If False, silently use alternative without warning.
                  Note: This only controls warning emission; selection order
                  is always preferred → alternative regardless of this flag.

    Returns:
        Path to runtime executable, or None if not found.
    """
    # Try preferred runtime first
    runtime_path = shutil.which(preferred)
    if runtime_path:
        return runtime_path

    # Try alternative
    alternative = "podman" if preferred == "docker" else "docker"
    runtime_path = shutil.which(alternative)
    if runtime_path:
        if explicit:
            print(
                f"Warning: {preferred} not found, using {alternative}", file=sys.stderr
            )
        return runtime_path

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
    Get the storage root directory for Docker or Podman.

    Args:
        runtime: Container runtime name ('docker' or 'podman')

    Returns:
        Storage root path as string, or None if command fails.
    """
    try:
        if runtime == "docker":
            result = subprocess.run(
                [runtime, "system", "info", "--format", "{{.DockerRootDir}}"],
                capture_output=True,
                check=False,
            )
            if result.stdout:
                return result.stdout.decode().strip()
        elif runtime == "podman":
            result = subprocess.run(
                [runtime, "info", "--format", "json"],
                capture_output=True,
                check=False,
            )
            if result.stdout:
                info = json.loads(result.stdout.decode())
                return info.get("store", {}).get("graphRoot")
        return None
    except OSError:
        return None


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
        # Clear the spinner line
        print(f"\r{' ' * 80}\r", end="", flush=True)


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
# Main entry point
# =============================================================================


def main() -> int:
    """Main entry point for the CLI."""
    args = parse_args()

    # Handle --check-update flag
    if args.check_update:
        check_for_update(force=True)
        return 0

    # Check for updates (daily, silent on errors)
    check_for_update(force=False)

    # Resolve timeout value: CLI > env > default 1200
    timeout = args.timeout or int(os.environ.get("MDIFY_TIMEOUT", 1200))

    # Validate input is provided
    if args.input is None:
        print("Error: Input file or directory is required", file=sys.stderr)
        print("Usage: mdify <input> [options]", file=sys.stderr)
        print("       mdify --help for more information", file=sys.stderr)
        return 1

    # Detect container runtime
    preferred = args.runtime if args.runtime else "docker"
    explicit = args.runtime is not None
    runtime = detect_runtime(preferred, explicit=explicit)
    if runtime is None:
        print(
            f"Error: Container runtime not found ({', '.join(SUPPORTED_RUNTIMES)})",
            file=sys.stderr,
        )
        print("Please install Docker or Podman to use mdify.", file=sys.stderr)
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

    if args.pull == "always" or (args.pull == "missing" and not image_exists):
        if not pull_image(runtime, image, args.quiet):
            print(f"Error: Failed to pull image: {image}", file=sys.stderr)
            return 1
    elif args.pull == "never" and not image_exists:
        print(f"Error: Image not found locally: {image}", file=sys.stderr)
        print(f"Run with --pull=missing or pull manually: {preferred} pull {image}")
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
            print(f"Starting docling-serve container...")
            print()

        with DoclingContainer(runtime, image, args.port, timeout=timeout) as container:
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
                    result = convert_file(
                        container.base_url, input_file, to_format="md"
                    )
                    elapsed = time.time() - start_time

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
                except Exception as e:
                    elapsed = time.time() - start_time
                    failed_count += 1
                    if not args.quiet:
                        spinner.stop()
                        print(
                            f"{progress} {input_file.name} ✗ ({format_duration(elapsed)})"
                        )
                        print(f"    Error: {str(e)}", file=sys.stderr)

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
