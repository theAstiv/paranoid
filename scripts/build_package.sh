#!/usr/bin/env bash
# Build Python package for PyPI distribution
#
# Usage:
#   ./scripts/build_package.sh
#
# Outputs:
#   dist/paranoid_cli-*.tar.gz (source distribution)
#   dist/paranoid_cli-*.whl (wheel)

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Paranoid Package Build Script ===${NC}"
echo ""

# Check if build module is installed
if ! python -m build --help &> /dev/null; then
    echo -e "${RED}ERROR: build module not found${NC}"
    echo "Install it with: pip install build"
    exit 1
fi

# Check if twine is installed (for checking)
if ! command -v twine &> /dev/null; then
    echo -e "${YELLOW}WARNING: twine not found (optional for checking)${NC}"
    echo "Install it with: pip install twine"
    TWINE_AVAILABLE=false
else
    TWINE_AVAILABLE=true
fi

# Clean previous builds
echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf build/ dist/ *.egg-info/

# Build package
echo -e "${BLUE}Building package...${NC}"
python -m build

# Check if build succeeded
if [ -d "dist" ] && [ "$(ls -A dist)" ]; then
    echo -e "${GREEN}✓ Build successful!${NC}"
    echo ""
    echo "Package files:"
    ls -lh dist/
    echo ""

    # Check package with twine if available
    if [ "$TWINE_AVAILABLE" = true ]; then
        echo -e "${BLUE}Checking package with twine...${NC}"
        twine check dist/*
        echo ""
    fi

    # Extract version from wheel filename
    WHEEL_FILE=$(ls dist/*.whl | head -n 1)
    VERSION=$(basename "$WHEEL_FILE" | sed 's/paranoid_cli-\(.*\)-py3.*/\1/')

    echo -e "${GREEN}✓ Package ready for distribution!${NC}"
    echo ""
    echo "Package: paranoid-cli v$VERSION"
    echo ""
    echo "To test locally:"
    echo "  pip install dist/paranoid_cli-$VERSION-py3-none-any.whl"
    echo ""
    echo "To publish to TestPyPI (for testing):"
    echo "  twine upload --repository testpypi dist/*"
    echo ""
    echo "To publish to PyPI (production):"
    echo "  twine upload dist/*"
    echo ""
    echo -e "${YELLOW}NOTE: GitHub Actions will automatically publish on git tag push${NC}"
else
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi
