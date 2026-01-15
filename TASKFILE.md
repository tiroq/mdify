# Task Commands Reference

This project uses [Task](https://taskfile.dev/) for automation. Task is a task runner / build tool that aims to be simpler and easier to use than Make.

## Installation

### macOS
```bash
brew install go-task/tap/go-task
```

### Linux
```bash
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin
```

### Other platforms
See https://taskfile.dev/installation/

## Quick Start

```bash
# Show all available tasks
task

# Build the package
task build

# Bump patch version and release
task release-patch
```

## Common Tasks

### Development

| Command | Description |
|---------|-------------|
| `task install` | Install package in development mode |
| `task clean` | Clean build artifacts and cache files |
| `task build` | Build package distributions (wheel and sdist) |
| `task check` | Check package with twine |
| `task test-install` | Test package installation in clean venv |

### Version Management

| Command | Description |
|---------|-------------|
| `task version` | Show current version |
| `task bump-patch` | Bump patch version (0.1.0 → 0.1.1) |
| `task bump-minor` | Bump minor version (0.1.0 → 0.2.0) |
| `task bump-major` | Bump major version (0.1.0 → 1.0.0) |
| `task commit-version` | Commit version bump changes |
| `task tag` | Create and push git tag |

### Publishing

| Command | Description |
|---------|-------------|
| `task publish-test` | Build and upload to TestPyPI |
| `task publish` | Build and upload to PyPI (production) |
| `task test-testpypi` | Test installation from TestPyPI |

### Complete Release Workflow

| Command | Description |
|---------|-------------|
| `task release-patch` | Complete patch release (bump → commit → tag → publish) |
| `task release-minor` | Complete minor release (bump → commit → tag → publish) |
| `task release-major` | Complete major release (bump → commit → tag → publish) |

## Release Workflow Examples

### Manual Step-by-Step

```bash
# 1. Bump version
task bump-patch          # or bump-minor, bump-major

# 2. Review changes
git diff

# 3. Commit version bump
task commit-version

# 4. Create and push git tag
task tag

# 5. Build package
task build

# 6. Test on TestPyPI (optional)
task publish-test
task test-testpypi

# 7. Publish to PyPI
task publish
```

### Automated Release

```bash
# One command for complete release
task release-patch       # Bumps, commits, tags, and publishes
```

The automated release will:
1. Bump the version
2. Ask for confirmation
3. Commit changes
4. Create and push git tag
5. Build the package
6. Upload to PyPI
7. Show link to create GitHub release

## Utility Tasks

| Command | Description |
|---------|-------------|
| `task setup-pypirc` | Create ~/.pypirc template |
| `task info` | Show package information |
| `task status` | Show git status and current version |
| `task push` | Push current branch and tags |

## Configuration

### PyPI Credentials

Before publishing, configure your PyPI credentials:

```bash
# Create .pypirc template
task setup-pypirc

# Edit ~/.pypirc and add your API tokens
# Get tokens from:
#   PyPI: https://pypi.org/manage/account/token/
#   TestPyPI: https://test.pypi.org/manage/account/token/
```

## Tips

- Always test with `task publish-test` before `task publish`
- Use `task build` to verify package builds correctly
- Run `task clean` if you encounter build issues
- Use `task version` to check current version
- Use `task status` to check git status and version

## Troubleshooting

**"Task not found"**: Install Task (see Installation section above)

**Build errors**: Run `task clean` then `task build`

**Authentication errors**: Check `~/.pypirc` has correct API tokens

**Version conflict**: The version in `pyproject.toml` and `mdify/__init__.py` must match
