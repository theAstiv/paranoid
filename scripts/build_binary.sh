#!/usr/bin/env bash
# Build standalone binary using PyInstaller
#
# Usage:
#   ./scripts/build_binary.sh
#
# Outputs:
#   dist/paranoid (Linux/macOS)
#   dist/paranoid.exe (Windows)

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Paranoid Binary Build Script ===${NC}"
echo ""

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo -e "${RED}ERROR: PyInstaller not found${NC}"
    echo "Install it with: pip install pyinstaller"
    exit 1
fi

# Check if spec file exists
if [ ! -f "paranoid.spec" ]; then
    echo -e "${RED}ERROR: paranoid.spec not found${NC}"
    echo "Run this script from the project root directory"
    exit 1
fi

# Clean previous builds
echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf build/ dist/

# Build binary
echo -e "${BLUE}Building binary with PyInstaller...${NC}"
pyinstaller paranoid.spec

# Check if build succeeded
if [ -f "dist/paranoid" ] || [ -f "dist/paranoid.exe" ]; then
    echo -e "${GREEN}✓ Build successful!${NC}"
    echo ""
    echo "Binary location:"
    if [ -f "dist/paranoid" ]; then
        ls -lh dist/paranoid
        BINARY="dist/paranoid"
    else
        ls -lh dist/paranoid.exe
        BINARY="dist/paranoid.exe"
    fi
    echo ""

    # Test the binary
    echo -e "${BLUE}Testing binary...${NC}"
    echo ""

    # Make executable on Unix
    if [ -f "dist/paranoid" ]; then
        chmod +x dist/paranoid
    fi

    # Test --help
    echo -e "${BLUE}Running: $BINARY --help${NC}"
    "$BINARY" --help
    echo ""

    # Test version
    echo -e "${BLUE}Running: $BINARY version${NC}"
    "$BINARY" version
    echo ""

    echo -e "${GREEN}✓ Binary is working correctly!${NC}"
    echo ""
    echo "To distribute:"
    echo "  - Linux:   tar -czf paranoid-linux-x64.tar.gz -C dist paranoid"
    echo "  - macOS:   tar -czf paranoid-macos-arm64.tar.gz -C dist paranoid"
    echo "  - Windows: zip paranoid-windows-x64.zip dist/paranoid.exe"
else
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi
