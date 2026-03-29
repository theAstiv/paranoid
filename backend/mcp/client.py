"""MCP client for code context extraction via context-link.

Manages context-link subprocess lifecycle and implements a three-tier
context extraction funnel: semantic search → code bodies → file skeletons.
"""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.mcp.errors import (
    MCPBinaryNotFoundError,
    MCPConnectionError,
    MCPTimeoutError,
    MCPToolError,
)
from backend.models.extended import CodeContext, CodeFile

logger = logging.getLogger(__name__)


class MCPCodeExtractor:
    """Async context manager for context-link MCP subprocess.

    Spawns context-link as a subprocess, communicates via MCP over stdio,
    and extracts code context using semantic search and file skeletons.
    """

    def __init__(
        self,
        project_root: str,
        binary_path: str | None = None,
        timeout_seconds: int = 120,
    ):
        """Initialize MCP code extractor.

        Args:
            project_root: Absolute path to repository root
            binary_path: Explicit path to context-link binary (optional)
            timeout_seconds: Timeout for MCP operations (default: 120s for initial indexing)
        """
        self.project_root = Path(project_root).resolve()
        self.binary_path = binary_path
        self.timeout_seconds = timeout_seconds
        self._session: ClientSession | None = None
        self._stdio_context = None

    async def __aenter__(self) -> "MCPCodeExtractor":
        """Start context-link subprocess and initialize MCP session."""
        binary = self._resolve_binary(self.binary_path)
        logger.info(f"Starting context-link from {binary} for {self.project_root}")

        server_params = StdioServerParameters(
            command=str(binary),
            args=["serve", str(self.project_root)],
            env=None,
        )

        try:
            # Create stdio context and session
            self._stdio_context = stdio_client(server_params)
            read, write = await asyncio.wait_for(
                self._stdio_context.__aenter__(),
                timeout=self.timeout_seconds,
            )
            self._session = ClientSession(read, write)
            await asyncio.wait_for(
                self._session.__aenter__(),
                timeout=self.timeout_seconds,
            )

            logger.info("context-link MCP session established")
            return self

        except asyncio.TimeoutError as e:
            logger.error(f"context-link startup timeout after {self.timeout_seconds}s")
            raise MCPTimeoutError(
                f"context-link did not start within {self.timeout_seconds}s"
            ) from e
        except Exception as e:
            logger.error(f"Failed to start context-link: {e}")
            raise MCPConnectionError(f"context-link subprocess failed: {e}") from e

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Teardown MCP session and terminate subprocess."""
        if self._session:
            try:
                await self._session.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")

        if self._stdio_context:
            try:
                await self._stdio_context.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"Error closing stdio context: {e}")

        logger.info("context-link subprocess terminated")

    def _resolve_binary(self, explicit_path: str | None) -> Path:
        """Resolve context-link binary location.

        Fallback chain: explicit path → CONTEXT_LINK_BINARY env var →
        ./bin/context-link → PATH lookup via shutil.which.

        Args:
            explicit_path: User-provided binary path (highest priority)

        Returns:
            Resolved Path to context-link binary

        Raises:
            MCPBinaryNotFoundError: Binary not found in any location
        """
        # 1. Explicit path
        if explicit_path:
            path = Path(explicit_path)
            if path.is_file():
                return path
            raise MCPBinaryNotFoundError(f"Explicit binary path not found: {explicit_path}")

        # 2. Environment variable
        env_path = os.getenv("CONTEXT_LINK_BINARY")
        if env_path:
            path = Path(env_path)
            if path.is_file():
                return path
            logger.warning(f"CONTEXT_LINK_BINARY set but not found: {env_path}")

        # 3. Local ./bin/ directory (relative to project root or cwd)
        for base in [Path.cwd(), Path(__file__).parent.parent.parent]:
            bin_path = base / "bin" / "context-link"
            if bin_path.is_file():
                return bin_path

        # 4. PATH lookup
        which_result = shutil.which("context-link")
        if which_result:
            return Path(which_result)

        raise MCPBinaryNotFoundError(
            "context-link binary not found. Set CONTEXT_LINK_BINARY or place in ./bin/"
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call MCP tool and extract result.

        Args:
            name: Tool name (e.g., "semantic_search_symbols")
            arguments: Tool arguments as dict

        Returns:
            Parsed tool result (typically dict or list)

        Raises:
            MCPToolError: Tool returned error response
            MCPTimeoutError: Tool call exceeded timeout
        """
        if not self._session:
            raise MCPConnectionError("MCP session not initialized")

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments=arguments),
                timeout=self.timeout_seconds,
            )

            # MCP tool results have .content list with text/image/resource items
            if not result.content:
                logger.warning(f"Tool {name} returned empty content")
                return None

            # Extract text content from first item
            first_item = result.content[0]
            if hasattr(first_item, "text"):
                text_content = first_item.text
                # Try to parse as JSON if it looks like JSON
                if text_content.strip().startswith(("{", "[")):
                    try:
                        return json.loads(text_content)
                    except json.JSONDecodeError:
                        return text_content
                return text_content

            logger.warning(f"Tool {name} returned non-text content")
            return None

        except asyncio.TimeoutError as e:
            logger.error(f"Tool {name} timeout after {self.timeout_seconds}s")
            raise MCPTimeoutError(f"Tool {name} exceeded timeout") from e
        except Exception as e:
            logger.error(f"Tool {name} error: {e}")
            raise MCPToolError(f"Tool {name} failed: {e}") from e

    async def search_symbols(self, query: str, top_k: int = 15) -> list[dict[str, Any]]:
        """Search for code symbols by semantic similarity.

        Args:
            query: Natural language description of what to find
            top_k: Maximum results to return

        Returns:
            List of symbol metadata dicts with keys: symbol_name, kind, file_path, similarity
        """
        try:
            result = await self._call_tool(
                "semantic_search_symbols",
                {"query": query, "top_k": top_k},
            )
            if isinstance(result, list):
                return result
            return []
        except (MCPToolError, MCPTimeoutError) as e:
            logger.warning(f"Symbol search failed: {e}")
            return []

    async def get_code_by_symbol(
        self, symbol_name: str, depth: int = 1
    ) -> dict[str, Any] | None:
        """Retrieve code for a symbol with dependencies.

        Args:
            symbol_name: Name or qualified name of symbol
            depth: Dependency depth (0 = symbol only, 1 = direct deps, max 3)

        Returns:
            Dict with keys: symbol, code, dependencies, imports
        """
        try:
            result = await self._call_tool(
                "get_code_by_symbol",
                {"symbol_name": symbol_name, "depth": depth},
            )
            return result if isinstance(result, dict) else None
        except (MCPToolError, MCPTimeoutError) as e:
            logger.warning(f"get_code_by_symbol({symbol_name}) failed: {e}")
            return None

    async def get_file_skeleton(self, file_path: str) -> dict[str, Any] | None:
        """Retrieve structural outline of a file (signatures only, no bodies).

        Args:
            file_path: Relative file path from repository root

        Returns:
            Dict with keys: file_path, symbols (list of signature dicts)
        """
        try:
            result = await self._call_tool(
                "get_file_skeleton",
                {"file_path": file_path},
            )
            return result if isinstance(result, dict) else None
        except (MCPToolError, MCPTimeoutError) as e:
            logger.warning(f"get_file_skeleton({file_path}) failed: {e}")
            return None

    async def extract_context(
        self, description: str, max_bytes: int = 50_000
    ) -> CodeContext:
        """Extract relevant code context using three-tier funnel.

        Strategy:
        1. Semantic search for top 15 relevant symbols
        2. Fetch code bodies (with depth=1 deps) for top results
        3. Fill remaining budget with file skeletons

        Args:
            description: System description for semantic search
            max_bytes: Maximum total bytes for all code content

        Returns:
            CodeContext with relevant files
        """
        files: list[CodeFile] = []
        total_bytes = 0
        seen_paths: set[str] = set()

        # Tier 1: Semantic search
        symbols = await self.search_symbols(description, top_k=15)
        if not symbols:
            logger.warning("Semantic search returned no symbols")
            return CodeContext(
                repository=str(self.project_root),
                files=[],
                summary=None,
            )

        # Tier 2: Fetch code bodies for top symbols (until budget exhausted)
        for symbol_meta in symbols:
            if total_bytes >= max_bytes:
                break

            symbol_name = symbol_meta.get("symbol_name")
            file_path = symbol_meta.get("file_path")

            if not symbol_name or not file_path:
                continue

            # Skip if we already have this file
            if file_path in seen_paths:
                continue

            code_data = await self.get_code_by_symbol(symbol_name, depth=1)
            if not code_data:
                continue

            # Extract code content
            code_text = code_data.get("code", "")
            language = symbol_meta.get("language")

            # Check budget
            content_bytes = len(code_text.encode("utf-8"))
            if total_bytes + content_bytes > max_bytes:
                logger.info(f"Budget exhausted at {len(files)} code files")
                break

            files.append(
                CodeFile(
                    path=file_path,
                    content=code_text,
                    language=language,
                )
            )
            seen_paths.add(file_path)
            total_bytes += content_bytes

        # Tier 3: Fill remaining budget with file skeletons
        if total_bytes < max_bytes:
            for symbol_meta in symbols:
                if total_bytes >= max_bytes:
                    break

                file_path = symbol_meta.get("file_path")
                if not file_path or file_path in seen_paths:
                    continue

                skeleton = await self.get_file_skeleton(file_path)
                if not skeleton:
                    continue

                # Serialize skeleton to text
                skeleton_text = json.dumps(skeleton, indent=2)
                content_bytes = len(skeleton_text.encode("utf-8"))

                if total_bytes + content_bytes > max_bytes:
                    break

                files.append(
                    CodeFile(
                        path=file_path,
                        content=skeleton_text,
                        language=symbol_meta.get("language"),
                    )
                )
                seen_paths.add(file_path)
                total_bytes += content_bytes

        logger.info(
            f"Extracted {len(files)} files ({total_bytes} bytes) from {self.project_root}"
        )

        return CodeContext(
            repository=str(self.project_root),
            files=files,
            summary=None,
        )
