# Publishing mdify to PyPI

This guide explains how to build and publish mdify to PyPI.

## Prerequisites

Install build tools:

```bash
pip install --upgrade build twine
```

## Build the Package

1. **Clean previous builds** (if any):

```bash
rm -rf build/ dist/ *.egg-info
```

2. **Build the distribution packages**:

```bash
python -m build
```

This creates:
- `dist/mdify-<version>.tar.gz` (source distribution)
- `dist/mdify-<version>-py3-none-any.whl` (wheel distribution)

## Test the Build Locally

Install the package locally to test:

```bash
pip install dist/mdify-<version>-py3-none-any.whl
```

Or test in a fresh virtual environment:

```bash
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate
pip install dist/mdify-<version>-py3-none-any.whl
mdify --version
deactivate
rm -rf test_env
```

## Upload to TestPyPI (Recommended First)

1. **Create an account** on [TestPyPI](https://test.pypi.org/account/register/)

2. **Create an API token** at https://test.pypi.org/manage/account/token/

3. **Upload to TestPyPI**:

```bash
python -m twine upload --repository testpypi dist/*
```

When prompted:
- Username: `__token__`
- Password: Your TestPyPI API token (including the `pypi-` prefix)

4. **Test installation from TestPyPI**:

```bash
pip install --index-url https://test.pypi.org/simple/ --no-deps mdify
```

Note: Use `--no-deps` because TestPyPI might not have all dependencies.

## Upload to PyPI (Production)

1. **Create an account** on [PyPI](https://pypi.org/account/register/)

2. **Create an API token** at https://pypi.org/manage/account/token/

3. **Upload to PyPI**:

```bash
python -m twine upload dist/*
```

When prompted:
- Username: `__token__`
- Password: Your PyPI API token (including the `pypi-` prefix)

4. **Verify the upload** at https://pypi.org/project/mdify/

## Using API Tokens with .pypirc

To avoid entering credentials each time, create `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR-PYPI-API-TOKEN

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR-TESTPYPI-API-TOKEN
```

Set proper permissions:

```bash
chmod 600 ~/.pypirc
```

Then upload without prompts:

```bash
python -m twine upload --repository testpypi dist/*  # TestPyPI
python -m twine upload dist/*                         # PyPI
```

## Version Bumping

Before publishing a new version:

1. Update version in [pyproject.toml](pyproject.toml):
   ```toml
   version = "0.2.0"
   ```

2. Update version in [mdify/__init__.py](mdify/__init__.py):
   ```python
   __version__ = "0.2.0"
   ```

3. Create a git tag:
   ```bash
   git tag -a v0.2.0 -m "Release version 0.2.0"
   git push origin v0.2.0
   ```

4. Create a GitHub release at https://github.com/tiroq/mdify/releases/new

## Complete Release Workflow

```bash
# 1. Update version numbers
vim pyproject.toml mdify/__init__.py

# 2. Commit changes
git add pyproject.toml mdify/__init__.py
git commit -m "Bump version to 0.2.0"
git push

# 3. Create and push tag
git tag -a v0.2.0 -m "Release version 0.2.0"
git push origin v0.2.0

# 4. Clean and build
rm -rf build/ dist/ *.egg-info
python -m build

# 5. Upload to TestPyPI first
python -m twine upload --repository testpypi dist/*

# 6. Test installation
pip install --index-url https://test.pypi.org/simple/ --no-deps mdify

# 7. If everything works, upload to PyPI
python -m twine upload dist/*

# 8. Create GitHub release with changelog
```

## Troubleshooting

**Package already exists error:**
- You cannot overwrite existing versions on PyPI
- Bump the version number and rebuild

**Missing dependencies on TestPyPI:**
- TestPyPI doesn't mirror all packages
- Use `--no-deps` flag when testing
- Full dependency test should be done on production PyPI

**Authentication errors:**
- Ensure you're using `__token__` as username
- Verify API token includes the `pypi-` prefix
- Check token hasn't expired

**Build errors:**
- Ensure `build` and `setuptools>=61.0` are installed
- Check pyproject.toml syntax
- Verify all required files exist (README.md, LICENSE)
