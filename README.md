# mdify

Convert documents to Markdown using the Docling library.

## Installation

### One-line install (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/tiroq/mdify/main/install.sh | bash
```

This will:
- Install mdify to `~/.mdify/`
- Create a virtual environment with all dependencies
- Add `mdify` command to your PATH

### Install via pip

```bash
pip install mdify
```

Or with user install (no sudo required):

```bash
pip install --user mdify
```

### Development install

```bash
git clone https://github.com/tiroq/mdify.git
cd mdify
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
- `--check-update`: Check for available updates and exit
- `--version`: Show version and exit

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

## Updates

mdify automatically checks for updates once per day. When a new version is available, you'll be prompted to upgrade:

```
==================================================
A new version of mdify is available!
  Current version: 0.1.0
  Latest version:  0.2.0
==================================================

Run upgrade now? [y/N]
```

### Manual upgrade

```bash
~/.mdify/install.sh --upgrade
```

### Check for updates manually

```bash
mdify --check-update
```

### Disable update checks

To disable automatic update checks, set the environment variable:

```bash
export MDIFY_NO_UPDATE_CHECK=1
```

Or for a single run:

```bash
MDIFY_NO_UPDATE_CHECK=1 mdify document.pdf
```

## Uninstall

```bash
~/.mdify/uninstall.sh
```

Or if installed via pip:

```bash
pip uninstall mdify
```

## License

MIT