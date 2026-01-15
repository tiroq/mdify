# Quick Start: Publishing to PyPI

## First Time Setup

1. **Create PyPI account** at <https://pypi.org/account/register/>
2. **Create API token** at <https://pypi.org/manage/account/token/>
   - Scope: "Entire account" for first upload, then project-specific
3. **Save token** in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-YOUR-API-TOKEN-HERE
```

```bash
chmod 600 ~/.pypirc
```

## Publishing a New Version

### 1. Update version numbers

```bash
# Edit both files to match
vim pyproject.toml      # version = "0.2.0"
vim mdify/__init__.py   # __version__ = "0.2.0"
```

### 2. Commit and tag

```bash
git add pyproject.toml mdify/__init__.py
git commit -m "Bump version to 0.2.0"
git tag -a v0.2.0 -m "Release version 0.2.0"
git push && git push --tags
```

### 3. Build and upload

```bash
./build.sh --upload
```

Or manually:

```bash
./build.sh
python3 -m twine upload dist/*
```

### 4. Create GitHub release

Go to <https://github.com/tiroq/mdify/releases/new>:
- Choose tag: v0.2.0
- Release title: mdify 0.2.0
- Add release notes
- Publish release

## Testing Before Production

Upload to TestPyPI first:

```bash
./build.sh --upload-test
```

Test installation:

```bash
pip install --index-url https://test.pypi.org/simple/ --no-deps mdify
```

## Checklist

- [ ] Version updated in `pyproject.toml`
- [ ] Version updated in `mdify/__init__.py`
- [ ] Changes committed and pushed
- [ ] Git tag created and pushed
- [ ] Package builds without errors (`./build.sh`)
- [ ] Package checks pass (twine)
- [ ] Tested on TestPyPI (optional but recommended)
- [ ] Uploaded to PyPI
- [ ] GitHub release created

## Common Issues

**"File already exists"**: Cannot overwrite versions on PyPI. Bump version number.

**Authentication failed**: Check API token in `~/.pypirc`, ensure `__token__` username.

**Missing dependencies on TestPyPI**: Use `--no-deps` flag when testing from TestPyPI.

For detailed instructions, see [PUBLISHING.md](PUBLISHING.md)
