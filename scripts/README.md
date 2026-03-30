# Build and Release Scripts

## Pre-Release Validation

Run the comprehensive build test before pushing any release:

```bash
# Install build dependencies first
pip install -e ".[build,dev]"

# Run all validation checks
python scripts/build_test.py
```

### What the build test validates:

1. **Version Consistency** - Checks version matches across pyproject.toml
2. **Test Suite** - Runs all 172+ tests
3. **Code Quality** - Runs ruff linting and formatting checks
4. **PyPI Package** - Builds wheel and source distribution
5. **Binary Build** - Creates platform-specific executable with PyInstaller
6. **Binary Smoke Test** - Tests --help and --version on built binary
7. **Dependency Check** - Verifies all required deps are listed
8. **Install Test** - Tests wheel can be installed in fresh virtualenv

### Output

The script creates release artifacts in `dist/`:
- `paranoid_cli-1.2.0-py3-none-any.whl` - PyPI wheel
- `paranoid_cli-1.2.0.tar.gz` - PyPI source distribution
- `paranoid-1.2.0-windows-amd64.exe` - Windows binary (on Windows)
- `paranoid-1.2.0-linux-x86_64` - Linux binary (on Linux)
- `paranoid-1.2.0-macos-arm64` - macOS binary (on macOS)

## Manual Binary Build

If you only want to build the binary (skip tests):

```bash
pyinstaller --clean --noconfirm paranoid.spec
```

Binary will be in `dist/paranoid/paranoid` (or `paranoid.exe` on Windows).

## PyPI Release Process

After `build_test.py` passes:

```bash
# Upload to TestPyPI first (optional but recommended)
twine upload --repository testpypi dist/*

# Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ paranoid-cli

# If all looks good, upload to production PyPI
twine upload dist/*
```

## GitHub Release Process

1. **Tag the release:**
   ```bash
   git tag -a v1.2.0 -m "Release v1.2.0"
   git push origin v1.2.0
   ```

2. **Create GitHub Release:**
   - Go to https://github.com/theAstiv/paranoid/releases/new
   - Select the tag v1.2.0
   - Title: "v1.2.0"
   - Copy changelog from CHANGELOG.md
   - Attach binaries:
     - `paranoid-1.2.0-windows-amd64.exe`
     - `paranoid-1.2.0-linux-x86_64`
     - `paranoid-1.2.0-macos-arm64`
   - Click "Publish release"

## Cross-Platform Builds

To build binaries for all platforms, you need to run the build on each platform:

### Windows (GitHub Actions or local):
```bash
python scripts/build_test.py
```
Produces: `paranoid-1.2.0-windows-amd64.exe`

### Linux (GitHub Actions or local):
```bash
python scripts/build_test.py
```
Produces: `paranoid-1.2.0-linux-x86_64`

### macOS (GitHub Actions or local):
```bash
python scripts/build_test.py
```
Produces: `paranoid-1.2.0-macos-arm64` (or `macos-x86_64` on Intel Macs)

## Automated Builds with GitHub Actions

You can automate this with GitHub Actions. Create `.github/workflows/release.yml`:

```yaml
name: Build and Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build-binaries:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ['3.12']

    runs-on: ${{ matrix.os }}

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install -e ".[build,dev]"

    - name: Run build test
      run: python scripts/build_test.py

    - name: Upload binaries
      uses: actions/upload-artifact@v4
      with:
        name: paranoid-${{ matrix.os }}
        path: dist/paranoid-*
```

## Troubleshooting

### PyInstaller build fails

- Check that all dependencies are installed: `pip install -e ".[build]"`
- Verify no import errors: `python -m cli.main --version`
- Check paranoid.spec has all necessary hiddenimports

### Tests fail

- Run tests individually to isolate: `pytest tests/test_file.py::test_name -v`
- Check Python version: must be 3.12+
- Verify all dev dependencies installed: `pip install -e ".[dev]"`

### Binary doesn't run

- Test in clean environment (fresh VM or container)
- Check error with: `./paranoid --help` (should show usage)
- Verify seeds/ directory was bundled: it's in paranoid.spec datas

### PyPI upload fails

- Check you have a PyPI account and API token
- Configure token: `twine upload --username __token__ --password pypi-...`
- Or use `~/.pypirc` config file
