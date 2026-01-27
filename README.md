# mdify

![mdify banner](https://raw.githubusercontent.com/tiroq/mdify/main/assets/mdify.png)

[![PyPI](https://img.shields.io/pypi/v/mdify-cli?logo=python&style=flat-square)](https://pypi.org/project/mdify-cli/)
[![Container](https://img.shields.io/badge/container-ghcr.io-blue?logo=docker&style=flat-square)](https://github.com/tiroq/mdify/pkgs/container/mdify-runtime)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)

A lightweight CLI for converting documents to Markdown. The CLI is fast to install via pipx, while the heavy ML conversion runs inside a container.

## Requirements

- **Python 3.8+**
- **Docker** or **Podman** (for document conversion)

## Installation

### macOS (recommended)

```bash
brew install pipx
pipx ensurepath
pipx install mdify-cli
```

Restart your terminal after installation.

### Linux

```bash
python3 -m pip install --user pipx
pipx ensurepath
pipx install mdify-cli
```

### Install via pip

```bash
pip install mdify-cli
```

### Development install

```bash
git clone https://github.com/tiroq/mdify.git
cd mdify
pip install -e .
```

## Usage

### Basic conversion

Convert a single file:
```bash
mdify document.pdf
```

The first run will automatically pull the container image (~2GB) if not present.

### Convert multiple files

Convert all PDFs in a directory:
```bash
mdify /path/to/documents -g "*.pdf"
```

Recursively convert files:
```bash
mdify /path/to/documents -r -g "*.pdf"
```

### GPU Acceleration

For faster processing with NVIDIA GPU:
```bash
mdify --gpu documents/*.pdf
```

Requires NVIDIA GPU with CUDA support and nvidia-container-toolkit.

### ⚠️ PII Masking (Deprecated)

The `--mask` flag is deprecated and will be ignored in this version. PII masking functionality was available in older versions using a custom runtime but is not supported with the current docling-serve backend.

If PII masking is critical for your use case, please use mdify v1.5.x or earlier versions.

## Performance

mdify now uses docling-serve for significantly faster batch processing:

- **Single model load**: Models are loaded once per session, not per file
- **~10-20x speedup** for multiple file conversions compared to previous versions
- **GPU acceleration**: Use `--gpu` for additional 2-6x speedup (requires NVIDIA GPU)

### First Run Behavior

The first conversion takes longer (~30-60s) as the container loads ML models into memory. Subsequent files in the same batch process quickly, typically in 1-3 seconds per file.

## Options

| Option | Description |
|--------|-------------|
| `input` | Input file or directory to convert (required) |
| `-o, --out-dir DIR` | Output directory for converted files (default: output) |
| `-g, --glob PATTERN` | Glob pattern for filtering files (default: *) |
| `-r, --recursive` | Recursively scan directories |
| `--flat` | Disable directory structure preservation |
| `--overwrite` | Overwrite existing output files |
| `-q, --quiet` | Suppress progress messages |
| `-m, --mask` | ⚠️ **Deprecated**: PII masking not supported in current version |
| `--gpu` | Use GPU-accelerated container (requires NVIDIA GPU and nvidia-container-toolkit) |
| `--port PORT` | Container port (default: 5001) |
| `--runtime RUNTIME` | Container runtime: docker or podman (auto-detected) |
| `--image IMAGE` | Custom container image (default: ghcr.io/docling-project/docling-serve-cpu:main) |
| `--pull POLICY` | Image pull policy: always, missing, never (default: missing) |
| `--check-update` | Check for available updates and exit |
| `--version` | Show version and exit |

### Flat Mode

With `--flat`, all output files are placed directly in the output directory. Directory paths are incorporated into filenames to prevent collisions:

- `docs/subdir1/file.pdf` → `output/subdir1_file.md`
- `docs/subdir2/file.pdf` → `output/subdir2_file.md`

## Examples

Convert all PDFs recursively, preserving structure:
```bash
mdify documents/ -r -g "*.pdf" -o markdown_output
```

Convert with Podman instead of Docker:
```bash
mdify document.pdf --runtime podman
```

Use a custom/local container image:
```bash
mdify document.pdf --image my-custom-image:latest
```

Force pull latest container image:
```bash
mdify document.pdf --pull
```

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────┐
│   mdify CLI      │     │  Container (Docker/Podman)      │
│   (lightweight)  │────▶│  ┌───────────────────────────┐  │
│                  │     │  │  Docling + ML Models      │  │
│  - File handling │◀────│  │  - PDF parsing            │  │
│  - Container     │     │  │  - OCR (Tesseract)        │  │
│    orchestration │     │  │  - Document conversion    │  │
└──────────────────┘     │  └───────────────────────────┘  │
                         └─────────────────────────────────┘
```

The CLI:
- Installs in seconds via pipx (no ML dependencies)
- Automatically detects Docker or Podman
- Pulls the runtime container on first use
- Mounts files and runs conversions in the container

## Container Images

mdify uses official docling-serve containers:

**CPU Version** (default):
```
ghcr.io/docling-project/docling-serve-cpu:main
```

**GPU Version** (use with `--gpu` flag):
```
ghcr.io/docling-project/docling-serve-cu126:main
```

These are official images from the [docling-serve project](https://github.com/DS4SD/docling-serve).

## Updates

mdify checks for updates daily. When a new version is available:

```
==================================================
A new version of mdify is available!
  Current version: 0.3.0
  Latest version:  0.4.0
==================================================

Run upgrade now? [y/N]
```

### Disable update checks

```bash
export MDIFY_NO_UPDATE_CHECK=1
```

## Uninstall

```bash
pipx uninstall mdify-cli
```

Or if installed via pip:

```bash
pip uninstall mdify-cli
```

## Development

### Task automation

This project uses [Task](https://taskfile.dev) for automation:

```bash
# Show available tasks
task

# Build package
task build

# Build container locally
task container-build

# Release workflow
task release-patch
```

### Building for PyPI

See [PUBLISHING.md](PUBLISHING.md) for complete publishing instructions.

## License

MIT
