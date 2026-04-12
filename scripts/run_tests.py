#!/usr/bin/env python3
"""Fast test runner for pre-commit/pre-merge validation.

Runs tests and code quality checks quickly. Use this in Git hooks
or for rapid feedback during development.

Usage:
    python scripts/run_tests.py           # Run everything
    python scripts/run_tests.py --fast    # Skip slow tests
    python scripts/run_tests.py --lint    # Only linting
    python scripts/run_tests.py --tests   # Only tests
"""

import argparse
import subprocess
import sys
from pathlib import Path


# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(msg: str) -> None:
    """Print section header."""
    print(f"\n{BLUE}{BOLD}{'=' * 70}{RESET}")
    print(f"{BLUE}{BOLD}>> {msg}{RESET}")
    print(f"{BLUE}{BOLD}{'=' * 70}{RESET}\n")


def print_success(msg: str) -> None:
    """Print success message."""
    print(f"{GREEN}[OK] {msg}{RESET}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"{RED}[FAIL] {msg}{RESET}")


def run_command(cmd: list[str], check: bool = True) -> bool:
    """Run command and return success status."""
    print(f"  Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=Path(__file__).parent.parent,
            check=check,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


def run_linting() -> bool:
    """Run code quality checks."""
    print_header("Code Quality Checks")

    # Check if ruff is available
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{YELLOW}⚠ ruff not installed, skipping linting{RESET}")
        return True

    success = True

    # Run ruff check
    print("\n  Linting code...")
    if not run_command(
        [sys.executable, "-m", "ruff", "check", "backend/", "cli/", "tests/"], check=False
    ):
        print_error("Linting failed")
        success = False
    else:
        print_success("Linting passed")

    # Run ruff format check
    print("\n  Checking code formatting...")
    if not run_command(
        [sys.executable, "-m", "ruff", "format", "--check", "backend/", "cli/", "tests/"],
        check=False,
    ):
        print_error("Code formatting check failed")
        print(f"{YELLOW}  Fix with: ruff format backend/ cli/ tests/{RESET}")
        success = False
    else:
        print_success("Code formatting passed")

    return success


def run_tests(fast_mode: bool = False) -> bool:
    """Run test suite."""
    print_header("Test Suite")

    cmd = [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"]

    if fast_mode:
        # Skip slow tests (integration, MCP)
        cmd.extend(["-m", "not slow", "--maxfail=3"])
        print(f"{YELLOW}  Running in fast mode (skipping slow tests){RESET}\n")

    success = run_command(cmd, check=False)

    if success:
        print_success("All tests passed")
    else:
        print_error("Some tests failed")

    return success


def main() -> None:
    """Run tests and quality checks."""
    parser = argparse.ArgumentParser(
        description="Run tests and code quality checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: skip slow tests, fail fast",
    )
    parser.add_argument(
        "--lint",
        action="store_true",
        help="Only run linting (no tests)",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="Only run tests (no linting)",
    )

    args = parser.parse_args()

    print(f"{BOLD}{BLUE}")
    print("=" * 70)
    print("               Paranoid Test Runner")
    print("=" * 70)
    print(f"{RESET}\n")

    success = True

    # Run linting (unless --tests only)
    if not args.tests:
        if not run_linting():
            success = False

    # Run tests (unless --lint only)
    if not args.lint:
        if not run_tests(fast_mode=args.fast):
            success = False

    # Print summary
    print(f"\n{BOLD}")
    print("=" * 70)
    if success:
        print(f"{GREEN}ALL CHECKS PASSED{RESET}")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"{RED}SOME CHECKS FAILED{RESET}")
        print("=" * 70)
        print(f"\n{YELLOW}Fix issues above before committing.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
