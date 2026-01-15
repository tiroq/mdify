# mdify

Convert documents to Markdown using the Docling library.

## Installation

```bash
pip install -e .
```

## Usage

Convert a single file:
```bash
mdify document.pdf
```

Convert all files in a directory:
```bash
mdify /path/to/documents --glob "*.pdf"
```

Recursively convert files in a directory:
```bash
mdify /path/to/documents --recursive --glob "*.pdf"
```

## Options

- `input`: Input file or directory to convert (required)
- `--out-dir DIR`: Output directory for converted files (default: output)
- `--glob PATTERN`: Glob pattern for filtering files in directory (default: *)
- `--recursive`: Recursively scan directories
- `--flat`: Disable directory structure preservation in output
- `--overwrite`: Overwrite existing output files
- `--quiet`: Suppress progress messages

### Flat Mode Behavior

When using `--flat`, all output files are placed directly in the output directory. To prevent name collisions when multiple input files have the same name (e.g., `dir1/file.pdf` and `dir2/file.pdf`), the directory path is incorporated into the filename:

- `docs/subdir1/file.pdf` → `output/subdir1_file.md`
- `docs/subdir2/file.pdf` → `output/subdir2_file.md`
- `docs/a/b/c/file.pdf` → `output/a_b_c_file.md`

## Examples

Convert all PDFs in a directory recursively, preserving structure:
```bash
mdify documents/ --recursive --glob "*.pdf" --out-dir markdown_output
```

Convert all documents to a flat output directory:
```bash
mdify documents/ --recursive --flat --out-dir all_docs
```

Overwrite existing files:
```bash
mdify documents/ --overwrite
```