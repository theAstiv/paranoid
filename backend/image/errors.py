"""Errors for diagram/image processing."""


class DiagramValidationError(Exception):
    """Raised when diagram file validation fails.

    Used by backend/image/validation.py. CLI layer catches this and
    re-raises as InputFileError for user-facing messages.
    """

    pass
