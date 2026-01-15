#!/usr/bin/env python3
"""CLI for converting documents to Markdown using Docling."""

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

from docling.document_converter import DocumentConverter


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert documents to Markdown using Docling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "input",
        type=str,
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

        stem = Path(parts[-1]).stem
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
