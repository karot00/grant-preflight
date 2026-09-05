"""Typed application errors (P1.3).

Service modules raise :class:`AppError`; the UI catches it and renders its
safe message. Callers log the code and exception class, not raw external
exception strings, SQL parameter values, source text, credentials, or profile
contents. Unknown exceptions are programming errors and are never swallowed
into success.
"""

ERROR_CODES = frozenset({
    "CONFIG_INVALID",
    "INPUT_INVALID",
    "URL_REJECTED",
    "FETCH_FAILED",
    "FETCH_TOO_LARGE",
    "UNSUPPORTED_CONTENT",
    "AI_UNAVAILABLE",
    "AI_REFUSED",
    "AI_INVALID",
    "AI_LIMIT",
    "STORAGE_UNAVAILABLE",
    "STORAGE_CONFLICT",
    "DRAFT_BLOCKED",
    "FIXTURE_MISMATCH",
})


class AppError(Exception):
    """Application error with a fixed code, a safe message, and a retry flag.

    ``message`` must be safe to display: it never contains credentials, raw
    external exception strings, source text, or profile contents. Constructing
    an ``AppError`` with a code outside :data:`ERROR_CODES` is a programming
    error and raises ``ValueError``.
    """

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown AppError code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
