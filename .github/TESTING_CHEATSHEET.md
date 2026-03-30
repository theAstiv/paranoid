# Testing Cheat Sheet

Quick reference for all testing commands in Paranoid.

## 🚀 Quick Commands

```bash
# Fast tests (during development)
python scripts/run_tests.py --fast

# Full tests (before commit)
python scripts/run_tests.py

# Pre-release validation (before tagging)
python scripts/build_test.py
# or: ./build-test.sh (Linux/Mac) or build-test.bat (Windows)

# Install Git hooks (one-time setup)
./scripts/install-hooks.sh  # Linux/Mac
scripts\install-hooks.bat   # Windows
```

## 📝 Test Script Options

### `run_tests.py` - Fast Test Runner

| Command | What it does | Duration |
|---------|-------------|----------|
| `python scripts/run_tests.py` | Full validation (lint + tests) | ~1-2 min |
| `python scripts/run_tests.py --fast` | Fast mode (skip slow tests) | ~20-30 sec |
| `python scripts/run_tests.py --lint` | Only linting (ruff) | ~5 sec |
| `python scripts/run_tests.py --tests` | Only tests (skip lint) | ~1 min |

### `build_test.py` - Pre-Release Validation

| Step | What it checks |
|------|---------------|
| 1 | Version consistency (pyproject.toml) |
| 2 | Full test suite (all 172+ tests) |
| 3 | Code quality (ruff check + format) |
| 4 | PyPI package build (.whl + .tar.gz) |
| 5 | Binary build (PyInstaller) |
| 6 | Binary smoke test (--help, --version) |
| 7 | Dependencies verification |
| 8 | Install test (fresh virtualenv) |

**Duration:** ~3-5 minutes

## 🪝 Git Hooks

| Hook | Runs on | Executes | Bypass |
|------|---------|----------|--------|
| pre-commit | `git commit` | `run_tests.py --fast` | `git commit --no-verify` |
| pre-push | `git push` | `run_tests.py` (full) | `git push --no-verify` |

**Install once:**
```bash
./scripts/install-hooks.sh     # Linux/Mac
scripts\install-hooks.bat      # Windows
```

## 🔬 Pytest Commands

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_pipeline_nodes.py -v

# Run specific test function
pytest tests/test_models.py::test_threat_creation -v

# Run tests matching pattern
pytest -k "diagram" -v

# Run with detailed output
pytest tests/test_dedup.py -vv

# Run and stop on first failure
pytest tests/ -x

# Run last failed tests
pytest --lf

# Show 10 slowest tests
pytest --durations=10
```

## 🧹 Code Quality

```bash
# Check linting
python -m ruff check backend/ cli/ tests/

# Auto-fix linting issues
python -m ruff check backend/ cli/ tests/ --fix

# Check formatting
python -m ruff format --check backend/ cli/ tests/

# Auto-format code
python -m ruff format backend/ cli/ tests/
```

## 🚀 GitHub Actions (CI/CD)

### Workflows

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| **test.yml** | Push to main/develop, PRs | Matrix tests (3 OS × 2 Python) + Lint |
| **pr-validation.yml** | PR opened/updated | Version check + Full tests + PR summary |
| **release.yml** | Tag push (`v*.*.*`) | Build binaries + PyPI + GitHub release |

### Check Status

```bash
# View workflow runs
https://github.com/theAstiv/paranoid/actions

# View specific PR checks
https://github.com/theAstiv/paranoid/pull/123/checks
```

## 📦 Release Process

```bash
# 1. Update version in pyproject.toml
version = "1.3.0"

# 2. Update CHANGELOG.md
## [1.3.0] - 2024-XX-XX
### Added
- Feature X

# 3. Run build test
./build-test.sh

# 4. Commit and tag
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 1.3.0"
git tag -a v1.3.0 -m "Release v1.3.0"

# 5. Push tag (triggers release workflow)
git push origin main
git push origin v1.3.0

# 6. GitHub Actions automatically:
#    - Builds binaries (Linux, macOS, Windows)
#    - Publishes to PyPI
#    - Creates GitHub release
```

## 🐛 Debugging Failed Tests

```bash
# Run with verbose output
pytest tests/test_failing.py -vv

# Run with full tracebacks
pytest tests/test_failing.py --tb=long

# Run with pdb on failure
pytest tests/test_failing.py --pdb

# Run with print statements visible
pytest tests/test_failing.py -s

# Run single test with all debug output
pytest tests/test_file.py::test_name -vvs --tb=long
```

## ⚡ Performance Tips

```bash
# Run tests in parallel (requires pytest-xdist)
pip install pytest-xdist
pytest tests/ -n auto

# Skip slow tests
pytest tests/ -m "not slow"

# Run only failed tests from last run
pytest --lf --tb=short

# Fast feedback loop during development
python scripts/run_tests.py --lint
# Fix linting issues, then:
python scripts/run_tests.py --fast
```

## 🔧 Environment Setup

```bash
# Fresh install (clean slate)
pip uninstall paranoid-cli -y
pip install -e ".[dev]"

# Install build dependencies
pip install -e ".[build,dev]"

# Verify installation
python -c "import backend, cli; print('✓ Import successful')"
python -m cli.main --version
```

## 📊 Coverage Reports

```bash
# Run tests with coverage
pytest tests/ --cov=backend --cov=cli --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows

# Coverage summary in terminal
pytest tests/ --cov=backend --cov=cli --cov-report=term-missing
```

## 🆘 Common Issues

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | `pip install -e ".[dev]"` |
| Tests pass locally, fail in CI | Check Python version: `python --version` (need 3.12+) |
| `ruff: command not found` | `pip install ruff` |
| Hook too slow | Already using `--fast`, or use `--no-verify` |
| PyPI publish fails | Check `PYPI_API_TOKEN` in GitHub repo settings |
| Binary build fails | Check `paranoid.spec` for missing `hiddenimports` |

## 📚 Documentation

- [TESTING.md](../TESTING.md) - Full testing guide
- [scripts/README.md](../scripts/README.md) - Build and release
- [.github/workflows/](../workflows/) - CI/CD workflows

---

**Need help?** Open an issue: https://github.com/theAstiv/paranoid/issues
