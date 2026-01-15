#!/usr/bin/env python3
"""
Container-side conversion script for mdify.

This script runs INSIDE the Docker/Podman container and uses Docling
to convert a single document to Markdown.

Usage:
    python convert.py --in /work/in/file.pdf --out /work/out/file.md
    python convert.py --in /work/in/file.pdf --out /work/out/file.md --mask
"""

import argparse
import sys
from pathlib import Path

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert a document to Markdown using Docling",
    )
    parser.add_argument(
        "--in",
        dest="input_file",
        type=str,
        required=True,
        help="Input file path",
    )
    parser.add_argument(
        "--out",
        dest="output_file",
        type=str,
        required=True,
        help="Output Markdown file path",
    )
    parser.add_argument(
        "--mask",
        action="store_true",
        help="Mask PII and sensitive content in images",
    )
    return parser.parse_args()


def convert(input_path: Path, output_path: Path, mask_pii: bool = False) -> int:
    """
    Convert a single file to Markdown.
    
    Args:
        input_path: Path to input document
        output_path: Path to output Markdown file
        mask_pii: Whether to mask PII/sensitive content in images
        
    Returns:
        0 on success, 1 on failure
    """
    try:
        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Configure pipeline options for PDF
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True
        
        if mask_pii:
            # Enable picture classification and image generation for masking
            pipeline_options.do_picture_classification = True
            pipeline_options.generate_picture_images = True
        
        # Initialize converter with format options
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
        
        # Convert document
        result = converter.convert(str(input_path))
        
        # Export to Markdown
        markdown_content = result.document.export_to_markdown()
        
        # Write output
        output_path.write_text(markdown_content, encoding="utf-8")
        
        print(f"Converted: {input_path.name} -> {output_path.name}")
        return 0
        
    except Exception as e:
        print(f"Error converting {input_path}: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    input_path = Path(args.input_file)
    output_path = Path(args.output_file)
    
    # Validate input exists
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1
    
    return convert(input_path, output_path, args.mask)


if __name__ == "__main__":
    sys.exit(main())
