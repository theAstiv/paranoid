#!/usr/bin/env bash
# Linux/macOS wrapper for build test script

set -e

echo ""
echo "========================================"
echo "  Paranoid Pre-Release Build Test"
echo "========================================"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found in PATH"
    exit 1
fi

# Use python3 explicitly on Unix
PYTHON=python3

# Check if build dependencies are installed
if ! $PYTHON -c "import build, twine, PyInstaller" &> /dev/null; then
    echo "Installing build dependencies..."
    $PYTHON -m pip install -e ".[build,dev]"
fi

# Run the build test
$PYTHON scripts/build_test.py
