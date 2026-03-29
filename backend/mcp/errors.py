"""MCP client exceptions.

Exception hierarchy for MCP-related errors, allowing graceful degradation
when code context extraction fails.
"""


class MCPError(Exception):
    """Base exception for all MCP-related errors."""

    pass


class MCPBinaryNotFoundError(MCPError):
    """Raised when context-link binary cannot be located."""

    pass


class MCPConnectionError(MCPError):
    """Raised when MCP subprocess fails to start or crashes."""

    pass


class MCPToolError(MCPError):
    """Raised when an MCP tool call returns an error response."""

    pass


class MCPTimeoutError(MCPError):
    """Raised when MCP operation exceeds timeout threshold."""

    pass
