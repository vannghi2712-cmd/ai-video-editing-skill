"""Domain exceptions for auto_video_editor."""


class AutoVideoEditorError(Exception):
    """Base exception for all auto_video_editor errors."""

    exit_code: int = 5  # Internal error default

    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ProfileNotFoundError(AutoVideoEditorError):
    """Raised when a profile ID cannot be resolved to a file."""

    exit_code = 3


class ProfilePathUnsafeError(AutoVideoEditorError):
    """Raised when a profile ID contains path traversal or unsafe characters."""

    exit_code = 3


class ProfileParseError(AutoVideoEditorError):
    """Raised when a profile JSON file cannot be parsed."""

    exit_code = 4


class ProfileValidationError(AutoVideoEditorError):
    """Raised when a merged profile fails business-rule validation."""

    exit_code = 4


class ProfileSchemaVersionError(AutoVideoEditorError):
    """Raised when a profile declares an unsupported schema version."""

    exit_code = 4
