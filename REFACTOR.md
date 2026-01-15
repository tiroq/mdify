# COPILOT_TASK.md — Repository Refactor: CLI + Container Runtime

## Goal

Refactor the repository so that:

* The Python CLI (`mdify`) is lightweight and installs fast via pipx
* Docling and all heavy ML dependencies run ONLY inside a Docker/Podman container
* The CLI orchestrates conversion by calling the container

## Target Architecture

### Host (CLI)

* PyPI package: mdify-cli
* Import package: mdify
* CLI command: mdify
* Responsibilities:

  * Parse CLI arguments
  * Discover input files (single file or directory + mask)
  * Compute output paths
  * Invoke container runtime per file (docker or podman)

### Container (Runtime)

* Contains Docling and heavy dependencies
* Exposes a simple entrypoint to convert one file to Markdown

Docling MUST NOT be a dependency of the PyPI package.

---

## Step 1 — Update Python Package Metadata

### pyproject.toml

* Ensure `[project].name = "mdify-cli"`
* REMOVE `docling` from `[project].dependencies`
* Keep dependencies minimal (prefer stdlib only)
* Keep console script:

```
[project.scripts]
mdify = "mdify.cli:main"
```

Do NOT rename the import package (`src/mdify/`).

---

## Step 2 — Refactor CLI Code (Host Side)

### mdify/cli.py

* REMOVE all direct imports of `docling`
* ADD container orchestration using `subprocess.run`

CLI must:

1. Resolve absolute paths using `pathlib.Path.resolve()`
2. For each input file, compute output `.md` path
3. Invoke container with mounted volumes

### New CLI flags

* `--runtime` (docker | podman), default: docker
* `--image`, default: `ghcr.io/<OWNER>/mdify-docling:latest`
* `--pull` (always | missing | never), default: missing

### Container invocation pattern

* Mount parent input directory as read-only
* Mount output directory as writable
* Pass container arguments:

  * `--in /work/in/<relative path>`
  * `--out /work/out/<relative path>.md`

Handle non-zero exit codes per file and continue batch processing.

---

## Step 3 — Add Container Runtime

### New directory: `runtime/`

#### runtime/Dockerfile

* Base image: python:3.12-slim
* Install Docling inside container
* Copy a single script: `convert.py`
* ENTRYPOINT must call convert.py

#### runtime/convert.py

* Accept `--in` and `--out`
* Use Docling to convert input file to Markdown
* Create parent directories for output
* Exit with non-zero code on failure

This script is the ONLY place where Docling is used.

---

## Step 4 — Repository Structure (Target)

```
src/
  mdify/
    __init__.py
    cli.py        # host CLI, no docling
runtime/
  Dockerfile     # docling image
  convert.py     # uses docling
pyproject.toml
README.md
```

---

## Step 5 — Update README.md

* Installation section MUST recommend:

```
pipx install mdify-cli
```

* Explain that Docker (or Podman) is required for actual conversion
* Document first-time image pull
* Provide example usage:

```
mdify ./docs -m "*.pdf" -r -o out/
```

---

## Step 6 — Error Handling & UX

* If container runtime is missing:

  * Print a clear error and exit code 2
* If container image is missing and pull=missing:

  * Pull automatically
* If a file fails:

  * Log error
  * Continue with remaining files
* Print final summary (OK / FAIL counts)

---

## Explicit Non-Goals

* No Docling import on host
* No ML dependencies in PyPI package
* No parallel execution (v1)
* No config files (YAML/TOML)

---

## Acceptance Criteria

* `pipx install mdify-cli` is fast (< few seconds)
* `mdify --help` works without Docker
* Conversion works only via container
* Repository cleanly separates CLI and runtime concerns
