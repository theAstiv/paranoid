"""File loading and validation for CLI input.

Loads .txt and .md files, validates size and content.
"""

from pathlib import Path

from cli.errors import InputFileError


# Maximum input file size (1MB)
MAX_FILE_SIZE = 1024 * 1024


def load_input_file(file_path: Path) -> str:
    """Load and validate input file.

    Args:
        file_path: Path to input file (.txt or .md)

    Returns:
        File contents as string

    Raises:
        InputFileError: File doesn't exist, is empty, or too large
    """
    # Check file exists
    if not file_path.exists():
        raise InputFileError(
            f"Input file not found: {file_path}\n\n"
            f"Make sure the file path is correct and the file exists."
        )

    # Check file is readable
    if not file_path.is_file():
        raise InputFileError(
            f"Path is not a file: {file_path}\n\n"
            f"Please provide a path to a .txt or .md file."
        )

    # Check file size
    file_size = file_path.stat().st_size
    if file_size == 0:
        raise InputFileError(
            f"Input file is empty: {file_path}\n\n"
            f"Please provide a file with system description content."
        )

    if file_size > MAX_FILE_SIZE:
        raise InputFileError(
            f"Input file too large: {file_size / 1024:.1f} KB (max: {MAX_FILE_SIZE / 1024:.0f} KB)\n\n"
            f"Please reduce file size or split into multiple threat models."
        )

    # Load file content
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise InputFileError(
            f"Failed to read file (encoding error): {file_path}\n\n"
            f"Make sure the file is UTF-8 encoded text.\n"
            f"Error: {e}"
        ) from e
    except Exception as e:
        raise InputFileError(
            f"Failed to read file: {file_path}\n\n" f"Error: {e}"
        ) from e

    # Validate content is not just whitespace
    if not content.strip():
        raise InputFileError(
            f"Input file contains only whitespace: {file_path}\n\n"
            f"Please provide a file with meaningful content."
        )

    return content
