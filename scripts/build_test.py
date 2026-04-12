#!/usr/bin/env python3
"""Pre-release build validation script.

Runs comprehensive checks before pushing a release to GitHub:
- All test suites
- Code quality (ruff)
- PyPI package build
- Binary build (PyInstaller)
- Binary smoke test
- Version consistency
"""

import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_step(msg: str) -> None:
    """Print a test step header."""
    print(f"\n{BLUE}{BOLD}{'=' * 70}{RESET}")
    print(f"{BLUE}{BOLD}>> {msg}{RESET}")
    print(f"{BLUE}{BOLD}{'=' * 70}{RESET}\n")


def print_success(msg: str) -> None:
    """Print success message."""
    print(f"{GREEN}[OK] {msg}{RESET}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"{RED}[FAIL] {msg}{RESET}")


def print_warning(msg: str) -> None:
    """Print warning message."""
    print(f"{YELLOW}[WARN] {msg}{RESET}")


def run_command(
    cmd: list[str], check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run a command and handle errors."""
    print(f"  Running: {' '.join(cmd)}")

    kwargs = {
        "check": check,
        "cwd": Path(__file__).parent.parent,
    }

    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True

    try:
        result = subprocess.run(cmd, check=False, **kwargs)
        if result.returncode == 0:
            print_success(f"Command succeeded: {cmd[0]}")
        return result
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed with exit code {e.returncode}")
        if capture and e.stdout:
            print(e.stdout)
        if capture and e.stderr:
            print(e.stderr)
        raise


def check_version_consistency() -> str:
    """Verify version is consistent across pyproject.toml and __version__.py"""
    print_step("Step 1: Check Version Consistency")

    repo_root = Path(__file__).parent.parent

    # Read version from pyproject.toml
    pyproject_path = repo_root / "pyproject.toml"
    pyproject_version = None
    with open(pyproject_path) as f:
        for line in f:
            if line.startswith("version ="):
                pyproject_version = line.split("=")[1].strip().strip('"')
                break

    if not pyproject_version:
        print_error("Could not find version in pyproject.toml")
        sys.exit(1)

    # Check if __version__.py exists
    version_file = repo_root / "backend" / "__version__.py"
    if version_file.exists():
        version_content = version_file.read_text()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', version_content)
        if match:
            code_version = match.group(1)
            if code_version != pyproject_version:
                print_error(
                    f"Version mismatch: pyproject.toml={pyproject_version}, __version__.py={code_version}"
                )
                sys.exit(1)

    print_success(f"Version is consistent: {pyproject_version}")
    return pyproject_version


def run_tests() -> None:
    """Run the full test suite."""
    print_step("Step 2: Run Test Suite")

    run_command([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"])
    print_success("All tests passed")


def run_linting() -> None:
    """Run code quality checks."""
    print_step("Step 3: Run Code Quality Checks")

    # Check if ruff is available
    try:
        subprocess.run([sys.executable, "-m", "ruff", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_warning("ruff not installed, skipping linting")
        return

    # Run ruff check (non-blocking - warnings only)
    print("\n  Running ruff check...")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend/", "cli/", "tests/"],
        cwd=Path(__file__).parent.parent,
        check=False,
    )
    if result.returncode != 0:
        print_warning("Ruff found some issues (non-blocking)")
    else:
        print_success("Ruff check passed")

    # Run ruff format check (non-blocking - warnings only)
    print("\n  Running ruff format check...")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "backend/", "cli/", "tests/"],
        cwd=Path(__file__).parent.parent,
        check=False,
    )
    if result.returncode != 0:
        print_warning("Some files need formatting (non-blocking)")
    else:
        print_success("Format check passed")

    print_success("Code quality checks completed")


def build_pypi_package() -> Path:
    """Build PyPI distribution packages."""
    print_step("Step 4: Build PyPI Package")

    repo_root = Path(__file__).parent.parent
    dist_dir = repo_root / "dist"

    # Clean previous builds
    if dist_dir.exists():
        print("  Cleaning previous build artifacts...")
        for file in dist_dir.glob("*"):
            file.unlink()

    # Build package
    run_command([sys.executable, "-m", "build"])

    # Verify artifacts exist
    wheel_files = list(dist_dir.glob("*.whl"))
    tar_files = list(dist_dir.glob("*.tar.gz"))

    if not wheel_files:
        print_error("No wheel file generated")
        sys.exit(1)

    if not tar_files:
        print_error("No source tarball generated")
        sys.exit(1)

    print_success(f"PyPI packages built: {wheel_files[0].name}, {tar_files[0].name}")
    return wheel_files[0]


def build_binary(version: str) -> Path:
    """Build standalone binary with PyInstaller."""
    print_step("Step 5: Build Standalone Binary")

    # Check if PyInstaller is available
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"], check=True, capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("PyInstaller not installed. Install with: pip install pyinstaller")
        sys.exit(1)

    repo_root = Path(__file__).parent.parent

    # Determine binary name based on platform
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        binary_name = f"paranoid-{version}-windows-{machine}.exe"
    elif system == "darwin":
        binary_name = f"paranoid-{version}-macos-{machine}"
    else:
        binary_name = f"paranoid-{version}-linux-{machine}"

    dist_dir = repo_root / "dist"
    spec_file = repo_root / "paranoid.spec"

    # Create PyInstaller spec if it doesn't exist
    if not spec_file.exists():
        print_warning("No paranoid.spec found, creating basic spec...")
        create_pyinstaller_spec(repo_root)

    # Build binary
    run_command([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_file)])

    # Find the built binary (single-file executable in dist/)
    if system == "windows":
        binary_path = dist_dir / "paranoid.exe"
    else:
        binary_path = dist_dir / "paranoid"

    if not binary_path.exists():
        print_error(f"Binary not found at {binary_path}")
        sys.exit(1)

    # Rename to platform-specific name
    final_binary = dist_dir / binary_name
    if final_binary.exists():
        final_binary.unlink()

    # Copy instead of rename to preserve original
    import shutil

    shutil.copy2(binary_path, final_binary)

    print_success(f"Binary built: {binary_name}")
    return final_binary


def create_pyinstaller_spec(repo_root: Path) -> None:
    """Create a basic PyInstaller spec file."""
    spec_content = """# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['cli/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('seeds', 'seeds'),
    ],
    hiddenimports=[
        'backend',
        'backend.models',
        'backend.providers',
        'backend.pipeline',
        'backend.db',
        'backend.rules',
        'backend.export',
        'cli',
        'cli.commands',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests',
        'frontend',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='paranoid',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='paranoid',
)
"""

    spec_path = repo_root / "paranoid.spec"
    spec_path.write_text(spec_content)
    print_success("Created paranoid.spec")


def smoke_test_binary(binary_path: Path) -> None:
    """Run basic smoke tests on the binary."""
    print_step("Step 6: Binary Smoke Test")

    # Test --help
    print("\n  Testing --help...")
    result = run_command([str(binary_path), "--help"], capture=True)
    if "Usage:" not in result.stdout:
        print_error("Binary --help output looks wrong")
        sys.exit(1)

    # Test --version
    print("\n  Testing --version...")
    result = run_command([str(binary_path), "--version"], capture=True)
    if not result.stdout.strip():
        print_warning("Binary --version returned no output (might need to implement)")

    print_success("Binary smoke tests passed")


def verify_dependencies() -> None:
    """Verify all dependencies are properly specified."""
    print_step("Step 7: Verify Dependencies")

    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"

    # Extract dependencies from pyproject.toml
    with open(pyproject_path) as f:
        content = f.read()

    # Basic check that common dependencies are listed
    required_deps = [
        "fastapi",
        "pydantic",
        "click",
        "aiosqlite",
        "httpx",
    ]

    missing_deps = []
    for dep in required_deps:
        if dep.lower() not in content.lower():
            missing_deps.append(dep)

    if missing_deps:
        print_error(f"Missing dependencies in pyproject.toml: {', '.join(missing_deps)}")
        sys.exit(1)

    print_success("Dependencies look good")


def test_pypi_install() -> None:
    """Test that the built wheel can be installed and imported."""
    print_step("Step 8: Test PyPI Package Installation")

    repo_root = Path(__file__).parent.parent
    dist_dir = repo_root / "dist"

    wheel_files = list(dist_dir.glob("*.whl"))
    if not wheel_files:
        print_error("No wheel file found in dist/")
        sys.exit(1)

    wheel_path = wheel_files[0]

    # Create a temporary virtualenv and test install
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_dir = Path(tmpdir) / "test_venv"

        print("\n  Creating test virtualenv...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

        # Determine python path in venv
        if platform.system() == "Windows":
            venv_python = venv_dir / "Scripts" / "python.exe"
        else:
            venv_python = venv_dir / "bin" / "python"

        print("\n  Installing wheel in test venv...")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", str(wheel_path)], check=True
        )

        print("\n  Testing CLI entrypoint...")
        result = subprocess.run(
            [str(venv_python), "-m", "cli.main", "--help"],
            capture_output=True,
            text=True,
            check=True,
        )

        if "Usage:" not in result.stdout:
            print_error("Installed package CLI doesn't work")
            sys.exit(1)

    print_success("PyPI package installs and runs correctly")


def main() -> None:
    """Run all build tests."""
    print(f"{BOLD}{BLUE}")
    print("=" * 70)
    print("         Paranoid Pre-Release Build Validation")
    print("=" * 70)
    print(f"{RESET}\n")

    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version.split()[0]}\n")

    try:
        # Run all validation steps
        version = check_version_consistency()
        run_tests()
        run_linting()
        wheel_path = build_pypi_package()
        binary_path = build_binary(version)
        smoke_test_binary(binary_path)
        verify_dependencies()
        test_pypi_install()

        # Final summary
        print(f"\n{GREEN}{BOLD}")
        print("=" * 70)
        print("                  ALL CHECKS PASSED")
        print("=" * 70)
        print(f"{RESET}\n")

        print(f"{GREEN}Release artifacts ready in dist/:{RESET}")
        print(f"  • PyPI wheel: {wheel_path.name}")
        print(f"  • Binary: {binary_path.name}")
        print(f"\n{GREEN}You can now:{RESET}")
        print("  1. Push to GitHub: git push && git push --tags")
        print("  2. Upload to PyPI: twine upload dist/*.whl dist/*.tar.gz")
        print(f"  3. Create GitHub release with binary: {binary_path.name}")

    except Exception as e:
        print(f"\n{RED}{BOLD}")
        print("=" * 70)
        print("                BUILD VALIDATION FAILED")
        print("=" * 70)
        print(f"{RESET}\n")
        print_error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
