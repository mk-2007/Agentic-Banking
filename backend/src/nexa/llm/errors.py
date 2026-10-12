"""Errors raised by the model gateway. Messages never contain API keys or prompt text."""

from nexa.domain.errors import DomainError


class LlmError(DomainError):
    """Base class for model gateway errors."""


class TransientLlmError(LlmError):
    """A failure worth retrying: rate limit, timeout, server error, empty answer."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LlmAuthError(LlmError):
    """The provider rejected the API key. Retrying the same provider will not help."""


class LlmRequestError(LlmError):
    """The provider rejected the request itself (bad model name, bad parameters)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AllProvidersFailedError(LlmError):
    """Every configured provider failed after retries."""


class BudgetExceededError(LlmError):
    """A case asked for more tokens than its budget allows."""


class StructuredOutputError(LlmError):
    """The model never produced valid output for the requested schema."""
