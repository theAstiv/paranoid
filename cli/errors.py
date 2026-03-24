"""CLI-specific exception types.

All CLI exceptions inherit from CLIError for easy catching and handling.
"""


class CLIError(Exception):
    """Base class for all CLI errors."""

    def __init__(self, message: str, exit_code: int = 1):
        """Initialize CLI error.

        Args:
            message: Human-readable error message
            exit_code: Exit code for the CLI (default: 1)
        """
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ConfigurationError(CLIError):
    """Configuration issues (missing API key, invalid provider, etc.)."""

    pass


class InputFileError(CLIError):
    """Input file issues (not found, malformed, too large, etc.)."""

    pass


class PipelineExecutionError(CLIError):
    """Pipeline runtime errors (LLM timeout, malformed response, etc.)."""

    pass


class OutputWriteError(CLIError):
    """Cannot write output file (permissions, disk space, etc.)."""

    pass
