#!/usr/bin/env python3
"""CLI for converting documents to Markdown using Docling."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from docling.document_converter import DocumentConverter

from . import __version__

# Configuration
MDIFY_HOME = Path.home() / ".mdify"
LAST_CHECK_FILE = MDIFY_HOME / ".last_check"
INSTALLER_PATH = MDIFY_HOME / "install.sh"
GITHUB_API_URL = "https://api.github.com/repos/tiroq/mdify/releases/latest"
CHECK_INTERVAL_SECONDS = 86400  # 24 hours


def _get_remote_version(timeout: int = 5) -> Optional[str]:
    """
    Fetch the latest version from GitHub API.
    
    Returns:
        Version string (e.g., "0.2.0") or None if fetch failed.
    """
    try:
        with urlopen(GITHUB_API_URL, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            # GitHub releases use tags like "v0.2.0" or "0.2.0"
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
    # Check if update check is disabled
    if os.environ.get("MDIFY_NO_UPDATE_CHECK", "").lower() in ("1", "true", "yes"):
        return False
    
    # Check if last check file exists
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
        pass  # Silently ignore write errors


def _compare_versions(current: str, remote: str) -> bool:
    """
    Compare version strings.
    
    Returns:
        True if remote version is newer than current.
    """
    try:
        current_parts = [int(x) for x in current.split(".")]
        remote_parts = [int(x) for x in remote.split(".")]
        
        # Pad shorter version with zeros
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
    # Skip check if not due (unless forced)
    if not force and not _should_check_for_update():
        return
    
    # Fetch remote version
    remote_version = _get_remote_version()
    
    if remote_version is None:
        if force:
            print(
                "Error: Failed to check for updates. "
                "Please check your internet connection.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Silently skip in auto mode
        return
    
    # Update last check time
    _update_last_check_time()
    
    # Compare versions
    if not _compare_versions(__version__, remote_version):
        if force:
            print(f"mdify is up to date (version {__version__})")
        return
    
    # Prompt for upgrade
    print(f"\n{'='*50}")
    print(f"A new version of mdify is available!")
    print(f"  Current version: {__version__}")
    print(f"  Latest version:  {remote_version}")
    print(f"{'='*50}\n")
    
    try:
        response = input("Run upgrade now? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()  # Newline for clean output
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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert documents to Markdown using Docling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "input",
        type=str,
        nargs="?",
        help="Input file or directory to convert",
    )
    
    parser.add_argument(
        "--out-dir",
        type=str,
        default="output",
        help="Output directory for converted files (default: output)",
    )
    
    parser.add_argument(
        "--glob",
        type=str,
        default="*",
        help="Glob pattern for filtering files in directory (default: *)",
    )
    
    parser.add_argument(
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
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    
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


def get_files_to_convert(input_path: Path, glob_pattern: str, recursive: bool) -> List[Path]:
    """Get list of files to convert based on input path and options."""
    files = []
    
    if input_path.is_file():
        files.append(input_path)
    elif input_path.is_dir():
        if recursive:
            # Use rglob for recursive search
            files = list(input_path.rglob(glob_pattern))
        else:
            # Use glob for non-recursive search
            files = list(input_path.glob(glob_pattern))
        
        # Filter to only files (exclude directories)
        files = [f for f in files if f.is_file()]
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    
    return files


def get_output_path(
    input_file: Path,
    input_base: Path,
    output_dir: Path,
    flat: bool,
) -> Path:
    """Calculate output path for a given input file."""
    if flat:
        # In flat mode, disambiguate files with the same name by incorporating
        # their relative directory components into the filename.
        try:
            relative_path = input_file.relative_to(input_base)
            parts = list(relative_path.parts)
        except ValueError:
            # If input_file is not relative to input_base, fall back to its name
            parts = [input_file.name]

        # Get stem from the filename (last part)
        stem = input_file.stem
        parent_prefix = "_".join(parts[:-1])
        if parent_prefix:
            output_name = f"{parent_prefix}_{stem}.md"
        else:
            output_name = f"{stem}.md"

        # Place all files directly in output directory with disambiguated names
        return output_dir / output_name
    else:
        # Preserve directory structure
        output_name = input_file.stem + ".md"
        try:
            relative_path = input_file.relative_to(input_base)
            output_path = output_dir / relative_path.parent / output_name
        except ValueError:
            # If input_file is not relative to input_base, place directly in output
            output_path = output_dir / output_name
        
        return output_path


def convert_file(
    converter: DocumentConverter,
    input_file: Path,
    output_file: Path,
    overwrite: bool,
    quiet: bool,
) -> Tuple[bool, str]:
    """
    Convert a single file to Markdown.
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    # Check if output file exists and overwrite is not set
    if output_file.exists() and not overwrite:
        msg = f"Skipped (exists): {input_file} -> {output_file}"
        if not quiet:
            print(msg)
        return False, "skipped"
    
    try:
        # Create output directory if it doesn't exist
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert document
        result = converter.convert(str(input_file))
        
        # Export to markdown
        markdown_content = result.document.export_to_markdown()
        
        # Write to output file
        output_file.write_text(markdown_content, encoding="utf-8")
        
        msg = f"Converted: {input_file} -> {output_file}"
        if not quiet:
            print(msg)
        
        return True, "success"
        
    except Exception as e:
        msg = f"Failed: {input_file} - {str(e)}"
        if not quiet:
            print(msg, file=sys.stderr)
        return False, f"error: {str(e)}"


def main() -> int:
    """Main entry point for the CLI."""
    args = parse_args()
    
    # Handle --check-update flag
    if args.check_update:
        check_for_update(force=True)
        return 0
    
    # Check for updates in background (daily, silent on errors)
    check_for_update(force=False)
    
    # Validate input is provided
    if args.input is None:
        print("Error: Input file or directory is required", file=sys.stderr)
        print("Usage: mdify <input> [options]", file=sys.stderr)
        return 1
    
    # Convert input to Path
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
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1
    
    if not files_to_convert:
        print(f"No files found to convert in: {input_path}", file=sys.stderr)
        return 1
    
    if not args.quiet:
        print(f"Found {len(files_to_convert)} file(s) to convert")
    
    # Determine input base for directory structure preservation
    if input_path.is_file():
        input_base = input_path.parent
    else:
        input_base = input_path
    
    # Initialize converter
    converter = DocumentConverter()
    
    # Convert files
    success_count = 0
    skipped_count = 0
    failed_count = 0
    
    for input_file in files_to_convert:
        output_file = get_output_path(input_file, input_base, output_dir, args.flat)
        success, result = convert_file(converter, input_file, output_file, args.overwrite, args.quiet)
        
        if success:
            success_count += 1
        elif result == "skipped":
            skipped_count += 1
        else:
            failed_count += 1
    
    # Print summary
    if not args.quiet:
        print("\n" + "=" * 50)
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
        return 0  # All files were skipped, but no errors
    elif success_count > 0:
        return 0  # At least some files were converted successfully
    else:
        return 1  # No files were converted


if __name__ == "__main__":
    sys.exit(main())
