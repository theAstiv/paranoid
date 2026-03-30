#!/usr/bin/env bash
# Install Git hooks for automatic testing
#
# Usage:
#   ./scripts/install-hooks.sh

set -e

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
HOOKS_DIR="$REPO_ROOT/.git/hooks"
SCRIPT_DIR="$REPO_ROOT/scripts/git-hooks"

echo ""
echo "Installing Git hooks..."
echo ""

# Check if we're in a git repository
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "❌ Not a git repository. Run this from inside the paranoid repo."
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p "$HOOKS_DIR"

# Install pre-commit hook
if [ -f "$SCRIPT_DIR/pre-commit" ]; then
    cp "$SCRIPT_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
    chmod +x "$HOOKS_DIR/pre-commit"
    echo "✅ Installed pre-commit hook (runs fast tests before commit)"
else
    echo "⚠️  pre-commit hook not found at $SCRIPT_DIR/pre-commit"
fi

# Install pre-push hook
if [ -f "$SCRIPT_DIR/pre-push" ]; then
    cp "$SCRIPT_DIR/pre-push" "$HOOKS_DIR/pre-push"
    chmod +x "$HOOKS_DIR/pre-push"
    echo "✅ Installed pre-push hook (runs full tests before push)"
else
    echo "⚠️  pre-push hook not found at $SCRIPT_DIR/pre-push"
fi

echo ""
echo "Git hooks installed successfully!"
echo ""
echo "Now when you:"
echo "  • git commit  → Fast tests run automatically"
echo "  • git push    → Full test suite runs automatically"
echo ""
echo "To bypass hooks (use sparingly):"
echo "  • git commit --no-verify"
echo "  • git push --no-verify"
echo ""
