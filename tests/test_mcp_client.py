"""Tests for MCP code extraction client.

These are simplified tests that verify the client can be instantiated
and basic error handling works. Full integration tests require actual
context-link binary.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.mcp.client import MCPCodeExtractor
from backend.mcp.errors import (
    MCPBinaryNotFoundError,
    MCPConnectionError,
)
from backend.models.extended import CodeContext


@pytest.mark.asyncio
async def test_init_with_explicit_path():
    """Test that MCPCodeExtractor can be initialized with explicit path."""
    extractor = MCPCodeExtractor(
        project_root="/test/repo",
        binary_path="/usr/local/bin/context-link",
        timeout_seconds=120,
    )
    assert extractor.project_root == Path("/test/repo").resolve()
    assert extractor.binary_path == "/usr/local/bin/context-link"
    assert extractor.timeout_seconds == 120


@pytest.mark.asyncio
async def test_init_with_auto_detection():
    """Test that MCPCodeExtractor can be initialized with None binary_path."""
    extractor = MCPCodeExtractor(
        project_root="/test/repo",
        binary_path=None,
    )
    assert extractor.project_root == Path("/test/repo").resolve()
    assert extractor.binary_path is None


@pytest.mark.asyncio
async def test_binary_not_found_error():
    """Test that MCPBinaryNotFoundError is raised when binary cannot be found."""
    with patch.dict("os.environ", {}, clear=True):
        with patch("pathlib.Path.is_file", return_value=False):
            with patch("shutil.which", return_value=None):
                extractor = MCPCodeExtractor(
                    project_root="/test/repo",
                    binary_path=None,
                )
                with pytest.raises(MCPBinaryNotFoundError):
                    async with extractor:
                        pass


@pytest.mark.asyncio
async def test_explicit_binary_path_not_found():
    """Test error when explicit binary path does not exist."""
    with patch("pathlib.Path.is_file", return_value=False):
        extractor = MCPCodeExtractor(
            project_root="/test/repo",
            binary_path="/nonexistent/context-link",
        )
        with pytest.raises(MCPBinaryNotFoundError, match="Explicit binary path not found"):
            async with extractor:
                pass


@pytest.mark.asyncio
async def test_connection_error_on_subprocess_failure():
    """Test MCPConnectionError when subprocess fails to start."""
    # Mock Path.is_file() to allow binary resolution
    with patch("pathlib.Path.is_file", return_value=True):
        with patch("backend.mcp.client.stdio_client") as mock_client:
            # Simulate subprocess failure
            mock_cm = AsyncMock()
            mock_cm.__aenter__.side_effect = Exception("Subprocess failed")
            mock_client.return_value = mock_cm

            extractor = MCPCodeExtractor(
                project_root="/test/repo",
                binary_path="/usr/local/bin/context-link",
            )
            with pytest.raises(MCPConnectionError, match="context-link"):
                async with extractor:
                    pass


@pytest.mark.asyncio
async def test_extract_context_respects_byte_budget():
    """Test that extraction stops when byte budget is exceeded."""
    # Create extractor but don't enter context (we're mocking the methods directly)
    extractor = MCPCodeExtractor(
        project_root="/test/repo",
        binary_path="/usr/local/bin/context-link",
    )

    # Mock the wrapper methods at the instance level
    extractor.search_symbols = AsyncMock(
        return_value=[
            {
                "symbol_name": "func1",
                "file_path": "file1.py",
                "kind": "function",
                "language": "python",
            },
            {
                "symbol_name": "func2",
                "file_path": "file2.py",
                "kind": "function",
                "language": "python",
            },
        ]
    )

    # First code fetch consumes most of budget (48KB), second would exceed it
    call_count = 0

    async def mock_get_code(symbol_name, depth=1):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: 48KB file (fits in budget)
            return {"code": "x" * 48_000, "symbol": {"name": "func1"}}
        # Second call: 5KB file (would exceed 50KB budget)
        return {"code": "y" * 5_000, "symbol": {"name": "func2"}}

    extractor.get_code_by_symbol = mock_get_code
    extractor.get_file_skeleton = AsyncMock(
        return_value={
            "file_path": "file2.py",
            "symbols": [{"name": "func2", "signature": "def func2(): pass"}],
        }
    )

    # Call extract_context with 50KB budget
    result = await extractor.extract_context("Test system", max_bytes=50_000)

    assert isinstance(result, CodeContext)
    assert result.repository == str(extractor.project_root)

    # Should have extracted first file as code (48KB) + second file as skeleton
    # Tier 2: file1.py code (48KB) - fits
    # Tier 2: file2.py code (5KB) - would exceed, skipped
    # Tier 3: file2.py skeleton (~100 bytes) - fits in remaining 2KB
    assert len(result.files) == 2

    # Verify total stays within budget
    total_bytes = sum(len(f.content.encode()) for f in result.files)
    assert total_bytes <= 50_000

    # Verify tier 3 was used for file2
    extractor.get_file_skeleton.assert_called_once_with("file2.py")


@pytest.mark.asyncio
async def test_extract_context_empty_search_results():
    """Test graceful handling when semantic search returns no results."""
    extractor = MCPCodeExtractor(
        project_root="/test/repo",
        binary_path="/usr/local/bin/context-link",
    )

    # Mock search_symbols to return empty results
    extractor.search_symbols = AsyncMock(return_value=[])
    extractor.get_code_by_symbol = AsyncMock()
    extractor.get_file_skeleton = AsyncMock()

    result = await extractor.extract_context("Nonexistent code", max_bytes=50_000)

    assert isinstance(result, CodeContext)
    assert result.repository == str(extractor.project_root)
    assert len(result.files) == 0

    # No code fetches should happen if search returns nothing
    extractor.get_code_by_symbol.assert_not_called()
    extractor.get_file_skeleton.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires actual context-link binary for integration test")
async def test_extract_context_integration():
    """Integration test for full extraction flow (requires context-link binary)."""
    # This test would require:
    # 1. Actual context-link binary available
    # 2. A real repository to analyze
    # 3. Full MCP protocol communication

    extractor = MCPCodeExtractor(
        project_root=".",
        binary_path="context-link",
    )
    async with extractor:
        context = await extractor.extract_context(
            description="Test system",
            max_bytes=50_000,
        )
        assert isinstance(context, CodeContext)
