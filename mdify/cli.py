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
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from . import __version__

# Configuration
MDIFY_HOME = Path.home() / ".mdify"
LAST_CHECK_FILE = MDIFY_HOME / ".last_check"
INSTALLER_PATH = MDIFY_HOME / "install.sh"
GITHUB_API_URL = "https://api.github.com/repos/tiroq/mdify/releases/latest"
CHECK_INTERVAL_SECONDS = 86400  # 24 hours

# Container configuration
DEFAULT_IMAGE = "ghcr.io/tiroq/mdify-runtime:latest"
SUPPORTED_RUNTIMES = ("docker", "podman")


# =============================================================================
# Update checking functions
# =============================================================================

def _get_remote_version(timeout: int = 5) -> Optional[str]:
    """
    Fetch the latest version from GitHub API.
    
    Returns:
        Version string (e.g., "0.2.0") or None if fetch failed.
    """
    try:
        with urlopen(GITHUB_API_URL, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
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


def _run_upgrade() -> bool:
    """
    Run the upgrade installer.
    
    Returns:
        True if upgrade was successful, False otherwise.
    """
    if not INSTALLER_PATH.exists():
        print(
            f"Installer not found at {INSTALLER_PATH}. "
            "Please reinstall mdify manually.",
            file=sys.stderr,
        )
        return False
    
    try:
        result = subprocess.run(
            [str(INSTALLER_PATH), "--upgrade", "-y"],
            check=True,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False
    except OSError as e:
        print(f"Failed to run installer: {e}", file=sys.stderr)
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
    
    print(f"\n{'='*50}")
    print(f"A new version of mdify is available!")
    print(f"  Current version: {__version__}")
    print(f"  Latest version:  {remote_version}")
    print(f"{'='*50}\n")
    
    try:
        response = input("Run upgrade now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    
    if response in ("y", "yes"):
        print("\nStarting upgrade...\n")
        if _run_upgrade():
            print("\nUpgrade completed! Please restart mdify.")
            sys.exit(0)
        else:
            print("\nUpgrade failed. You can try manually with:")
            print(f"  {INSTALLER_PATH} --upgrade")
    else:
        print(f"\nTo upgrade later, run: {INSTALLER_PATH} --upgrade\n")


# =============================================================================
# Container runtime functions
# =============================================================================

def detect_runtime(preferred: str) -> Optional[str]:
    """
    Detect available container runtime.
    
    Args:
        preferred: Preferred runtime ('docker' or 'podman')
        
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
        print(f"Warning: {preferred} not found, using {alternative}", file=sys.stderr)
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


def run_container(
    runtime: str,
    image: str,
    input_file: Path,
    output_file: Path,
    mask_pii: bool = False,
    quiet: bool = False,
) -> Tuple[bool, str]:
    """
    Run container to convert a single file.
    
    Args:
        runtime: Path to container runtime
        image: Image name/tag
        input_file: Absolute path to input file
        output_file: Absolute path to output file
        mask_pii: Whether to mask PII in images
        quiet: Suppress progress output
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Mount directories
    input_dir = input_file.parent
    output_dir = output_file.parent
    
    # Container paths
    container_in = f"/work/in/{input_file.name}"
    container_out = f"/work/out/{output_file.name}"
    
    cmd = [
        runtime, "run", "--rm",
        "-v", f"{input_dir}:/work/in:ro",
        "-v", f"{output_dir}:/work/out",
        image,
        "--in", container_in,
        "--out", container_out,
    ]
    
    if mask_pii:
        cmd.append("--mask")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode == 0:
            if not quiet:
                print(f"Converted: {input_file} -> {output_file}")
            return True, "success"
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            if not quiet:
                print(f"Failed: {input_file} - {error_msg}", file=sys.stderr)
            return False, f"error: {error_msg}"
            
    except OSError as e:
        if not quiet:
            print(f"Failed: {input_file} - {e}", file=sys.stderr)
        return False, f"error: {e}"


# =============================================================================
# File handling functions
# =============================================================================

# Supported file extensions (based on Docling InputFormat)
SUPPORTED_EXTENSIONS = {
    '.pdf', '.docx', '.pptx', '.html', '.htm',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif',  # images
    '.asciidoc', '.adoc', '.asc',  # asciidoc
    '.md', '.markdown',  # markdown
    '.csv', '.xlsx',  # spreadsheets
    '.xml',  # XML formats
    '.json',  # JSON docling
    '.mp3', '.wav', '.m4a', '.flac',  # audio
    '.vtt',  # subtitles
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
        f for f in files
        if not f.name.startswith('.')
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
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
        "-o", "--out-dir",
        type=str,
        default="output",
        help="Output directory for converted files (default: output)",
    )
    
    parser.add_argument(
        "-g", "--glob",
        type=str,
        default="*",
        help="Glob pattern for filtering files in directory (default: *)",
    )
    
    parser.add_argument(
        "-r", "--recursive",
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
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    
    parser.add_argument(
        "-m", "--mask",
        action="store_true",
        help="Mask PII and sensitive content in document images",
    )
    
    # Container options
    parser.add_argument(
        "--runtime",
        type=str,
        choices=SUPPORTED_RUNTIMES,
        default="docker",
        help="Container runtime to use (default: docker)",
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
    
    # Validate input is provided
    if args.input is None:
        print("Error: Input file or directory is required", file=sys.stderr)
        print("Usage: mdify <input> [options]", file=sys.stderr)
        print("       mdify --help for more information", file=sys.stderr)
        return 1
    
    # Detect container runtime
    runtime = detect_runtime(args.runtime)
    if runtime is None:
        print(
            f"Error: Container runtime not found ({', '.join(SUPPORTED_RUNTIMES)})",
            file=sys.stderr,
        )
        print("Please install Docker or Podman to use mdify.", file=sys.stderr)
        return 2
    
    # Handle image pull policy
    image = args.image
    image_exists = check_image_exists(runtime, image)
    
    if args.pull == "always" or (args.pull == "missing" and not image_exists):
        if not pull_image(runtime, image, args.quiet):
            print(f"Error: Failed to pull image: {image}", file=sys.stderr)
            return 1
    elif args.pull == "never" and not image_exists:
        print(f"Error: Image not found locally: {image}", file=sys.stderr)
        print(f"Run with --pull=missing or pull manually: {args.runtime} pull {image}")
        return 1
    
    # Resolve paths
    input_path = Path(args.input).resolve()
    output_dir = Path(args.out_dir).resolve()
    
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
    
    if not args.quiet:
        print(f"Found {len(files_to_convert)} file(s) to convert")
        print(f"Using runtime: {runtime}")
        print(f"Using image: {image}")
        print()
    
    # Determine input base for directory structure preservation
    if input_path.is_file():
        input_base = input_path.parent
    else:
        input_base = input_path
    
    # Convert files
    success_count = 0
    skipped_count = 0
    failed_count = 0
    
    for input_file in files_to_convert:
        output_file = get_output_path(input_file, input_base, output_dir, args.flat)
        
        # Check if output exists and skip if not overwriting
        if output_file.exists() and not args.overwrite:
            if not args.quiet:
                print(f"Skipped (exists): {input_file} -> {output_file}")
            skipped_count += 1
            continue
        
        success, result = run_container(
            runtime, image, input_file, output_file, args.mask, args.quiet
        )
        
        if success:
            success_count += 1
        else:
            failed_count += 1
    
    # Print summary
    if not args.quiet:
        print()
        print("=" * 50)
        print("Conversion Summary:")
        print(f"  Total files:     {len(files_to_convert)}")
        print(f"  Successful:      {success_count}")
        print(f"  Skipped:         {skipped_count}")
        print(f"  Failed:          {failed_count}")
        print("=" * 50)
    
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
