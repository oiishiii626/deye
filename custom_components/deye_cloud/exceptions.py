"""Custom exceptions for the Deye Cloud integration."""


class DeyeCloudError(Exception):
    """Base exception for Deye Cloud integration errors."""


class DeyeAuthError(DeyeCloudError):
    """Raised on 401 responses or invalid/expired tokens.

    Response: Refresh token → retry → repair flow after 3 failures.
    """


class DeyeApiError(DeyeCloudError):
    """Raised on non-401 4xx HTTP responses from the Deye Cloud API.

    Response: Log warning, raise to caller, revert optimistic state.
    """

    def __init__(self, message: str, error_code: str | None = None) -> None:
        """Initialize with optional API error code."""
        super().__init__(message)
        self.error_code = error_code


class DeyeTimeoutError(DeyeCloudError):
    """Raised when an API request exceeds the 30s timeout.

    Response: Retry with backoff (coordinator) or raise HomeAssistantError (service).
    """


class DeyeRateLimitError(DeyeCloudError):
    """Raised on HTTP 429 responses from the Deye Cloud API.

    Response: Pause polling for Retry-After duration (max 300s).
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        """Initialize with optional Retry-After value in seconds."""
        super().__init__(message)
        self.retry_after = retry_after


class DeyeConnectionError(DeyeCloudError):
    """Raised on DNS or TCP connection failures to the Deye Cloud API.

    Response: Retry with backoff, track consecutive failures.
    """


class OpenMeteoError(Exception):
    """Raised on Open-Meteo forecast API failures.

    Response: Retain stale data, mark forecast sensors as stale.
    """
