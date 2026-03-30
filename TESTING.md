# Testing and CI/CD Guide

This document explains the testing automation setup for the Paranoid project.

## 🎯 Quick Start

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
python scripts/run_tests.py

# Run tests in fast mode (skip slow tests)
python scripts/run_tests.py --fast

# Run only linting
python scripts/run_tests.py --lint

# Run only tests
python scripts/run_tests.py --tests
```

## 📋 Test Scripts Overview

### 1. `scripts/run_tests.py` - Fast Test Runner

**Purpose:** Quick validation during development and in Git hooks.

**Features:**
- Runs ruff linting and formatting checks
- Runs pytest test suite
- Fast mode (`--fast`) for quick feedback
- Colored output for easy reading

**Usage:**
```bash
python scripts/run_tests.py           # Full validation
python scripts/run_tests.py --fast    # Fast mode (skip slow tests)
python scripts/run_tests.py --lint    # Only linting
python scripts/run_tests.py --tests   # Only tests
```

### 2. `scripts/build_test.py` - Pre-Release Validation

**Purpose:** Comprehensive validation before GitHub releases.

**Features:**
- Version consistency check
- Full test suite
- Code quality checks
- PyPI package build + validation
- Binary build (PyInstaller)
- Binary smoke test
- Dependency verification
- Install test in fresh virtualenv

**Usage:**
```bash
python scripts/build_test.py
# or
./build-test.sh   # Linux/Mac
build-test.bat    # Windows
```

**When to use:** Before tagging a release or pushing to main.

## 🪝 Git Hooks (Local Validation)

Git hooks automatically run tests before commits and pushes.

### Installation

**Linux/macOS:**
```bash
./scripts/install-hooks.sh
```

**Windows:**
```bash
scripts\install-hooks.bat
```

### What Gets Installed

1. **pre-commit hook**
   - Runs before every `git commit`
   - Executes: `python scripts/run_tests.py --fast`
   - Fast tests only (< 30 seconds)
   - Bypass with: `git commit --no-verify`

2. **pre-push hook**
   - Runs before every `git push`
   - Executes: `python scripts/run_tests.py`
   - Full test suite (1-2 minutes)
   - Bypass with: `git push --no-verify`

### Hook Behavior

```bash
# Normal commit - runs fast tests
git commit -m "Fix bug"
# → Runs linting + fast tests

# Commit with --no-verify - skips tests
git commit --no-verify -m "WIP: testing"
# → Skips all checks

# Normal push - runs full tests
git push origin main
# → Runs linting + full test suite

# Push with --no-verify - skips tests
git push --no-verify
# → Skips all checks (use sparingly!)
```

## 🚀 GitHub Actions (CI/CD)

### 1. Test Workflow (`.github/workflows/test.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`

**What it does:**
- Runs on Ubuntu, Windows, macOS
- Tests Python 3.12 and 3.13
- Runs linting (ruff check + format check)
- Runs full test suite
- Uploads coverage reports (Ubuntu only)

**Matrix testing:**
```
OS: [ubuntu-latest, windows-latest, macos-latest]
Python: [3.12, 3.13]
= 6 test jobs total
```

### 2. PR Validation Workflow (`.github/workflows/pr-validation.yml`)

**Triggers:**
- Pull request opened, synchronized, or reopened
- Skips draft PRs

**What it does:**
- Version consistency check
- Linting (ruff)
- Full test suite with JUnit XML output
- Publishes test results to PR
- Checks for new TODO/FIXME comments
- Generates PR summary

**PR checks visible in GitHub:**
```
✓ validate-pr / Validate Pull Request
  ├─ Version consistency
  ├─ Linting
  ├─ Full test suite
  └─ PR summary
```

### 3. Release Workflow (`.github/workflows/release.yml`)

**Triggers:**
- Git tag push: `v*.*.*` (e.g., `v1.2.0`)

**What it does:**
- **Build binaries:**
  - Linux (x86_64)
  - macOS (arm64)
  - Windows (x64)
  - Tests each binary with `--help` and `version`

- **Build PyPI packages:**
  - Wheel (`.whl`)
  - Source distribution (`.tar.gz`)
  - Validates with `twine check`

- **Publish to PyPI:**
  - Uses trusted publishing (OIDC)
  - Requires PyPI environment configured in repo settings

- **Create GitHub Release:**
  - Attaches all binaries
  - Attaches PyPI packages
  - Extracts changelog from CHANGELOG.md
  - Marks as non-draft, non-prerelease

**Artifact names:**
```
paranoid-linux-x64
paranoid-macos-arm64
paranoid-windows-x64.exe
paranoid_cli-1.2.0-py3-none-any.whl
paranoid_cli-1.2.0.tar.gz
```

## 📊 Test Coverage

Current test suite breakdown:

```
Total tests: 172+

By category:
- CLI tests: 16
- Database tests: 12
- Model tests: 24
- Pipeline tests: 38
- Provider tests: 7
- Deduplication tests: 16
- Export tests: 6
- Image/diagram tests: 36
- MCP tests: 8
- SARIF tests: 6
- Other: 3+
```

## 🔍 Test Types

### Unit Tests
- Test individual functions/classes in isolation
- Fast (< 0.1s per test)
- Mock external dependencies
- Example: `test_models.py`, `test_dedup.py`

### Integration Tests
- Test multiple components together
- Slower (0.1-1s per test)
- May use real SQLite, real file I/O
- Example: `test_pipeline_nodes.py`, `test_db_crud.py`

### CLI Tests
- Test CLI commands end-to-end
- Use temporary directories
- Example: `test_cli_run_code.py`, `test_cli_run_diagram.py`

### Slow Tests (marked with `@pytest.mark.slow`)
- Integration tests requiring external services
- MCP server interaction
- Currently skipped in `--fast` mode

## 🛠️ Development Workflow

### 1. Local Development

```bash
# Make changes
vim backend/pipeline/nodes.py

# Run fast tests frequently
python scripts/run_tests.py --fast

# Run full tests before committing
python scripts/run_tests.py

# Commit (pre-commit hook runs automatically)
git commit -m "feat: add new pipeline step"

# Push (pre-push hook runs automatically)
git push origin feature-branch
```

### 2. Creating a Pull Request

1. **Push your branch:**
   ```bash
   git push origin feature-branch
   ```

2. **Create PR on GitHub:**
   - GitHub Actions runs PR validation automatically
   - Check status at: `https://github.com/theAstiv/paranoid/actions`

3. **Wait for CI:**
   - All 6 test matrix jobs must pass
   - PR validation must pass
   - Review any failures and push fixes

4. **Merge:**
   - Once approved and CI passes, merge to main
   - GitHub Actions runs test suite on main

### 3. Creating a Release

1. **Update version:**
   ```bash
   # Edit pyproject.toml
   version = "1.3.0"

   # Update CHANGELOG.md
   ## [1.3.0] - 2024-XX-XX
   ### Added
   - New feature X
   ```

2. **Run build test:**
   ```bash
   python scripts/build_test.py
   # or
   ./build-test.sh
   ```

3. **Commit and tag:**
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to 1.3.0"
   git tag -a v1.3.0 -m "Release v1.3.0"
   git push origin main
   git push origin v1.3.0
   ```

4. **GitHub Actions automatically:**
   - Builds binaries for all platforms
   - Builds PyPI packages
   - Publishes to PyPI
   - Creates GitHub release with all artifacts

## 🚨 Troubleshooting

### Tests fail locally but pass in CI
- Check Python version: `python --version` (must be 3.12+)
- Clean install: `pip install -e ".[dev]" --force-reinstall`
- Clear pytest cache: `rm -rf .pytest_cache`

### Pre-commit hook is too slow
- Use `git commit --no-verify` sparingly
- Or modify `.git/hooks/pre-commit` to use `--fast` mode (already enabled)

### GitHub Actions fail on specific platform
- Check the specific job logs in GitHub Actions tab
- Test locally on that platform (or use a VM/container)
- Common issues:
  - Windows path separators (`\` vs `/`)
  - macOS permission issues (use `chmod +x`)

### PyPI publish fails
- Check that `PYPI_API_TOKEN` secret is configured in repo settings
- Verify version isn't already published: https://pypi.org/project/paranoid-cli/
- Check trusted publishing is configured: https://pypi.org/manage/account/publishing/

### Binary build fails
- Check `paranoid.spec` has all necessary `hiddenimports`
- Test manually: `pyinstaller --clean --noconfirm paranoid.spec`
- Check binary runs: `./dist/paranoid --help`

## 📝 Adding New Tests

### Where to put tests

```
tests/
├── test_models.py           # Pydantic model tests
├── test_pipeline_nodes.py   # Pipeline step tests
├── test_providers_*.py      # LLM provider tests
├── test_db_crud.py          # Database CRUD tests
├── test_export_*.py         # Export format tests
├── test_cli_*.py            # CLI command tests
└── fixtures/                # Test fixtures and helpers
```

### Test naming conventions

```python
# Good test names (descriptive, behavior-focused)
def test_summarize_returns_summary_state()
def test_extract_assets_raises_on_provider_error()
def test_dedup_removes_identical_threats()

# Bad test names (implementation-focused)
def test_function_returns_dict()
def test_call_api()
```

### Running specific tests

```bash
# Run one test file
pytest tests/test_models.py -v

# Run one test function
pytest tests/test_models.py::test_threat_creation -v

# Run tests matching pattern
pytest -k "threat" -v

# Run with verbose output
pytest tests/test_pipeline_nodes.py -vv
```

## 🎓 Best Practices

1. **Run tests before committing** - The pre-commit hook helps, but run manually during development
2. **Write tests for bug fixes** - Add a failing test, then fix it
3. **Keep tests fast** - Mock external services, use small test data
4. **Use descriptive test names** - Test names are documentation
5. **One assertion per test** - Makes failures easier to debug
6. **Don't skip CI** - Never use `--no-verify` without good reason

## 📚 Related Documentation

- [scripts/README.md](scripts/README.md) - Build and release process
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines (if exists)
- [.github/workflows/](. github/workflows/) - CI/CD workflow definitions
