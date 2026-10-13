"""The interface every model provider implements."""

from typing import Protocol

from .messages import LlmRequest, LlmResponse


class LlmProvider(Protocol):
    """One model behind one endpoint."""

    @property
    def name(self) -> str:
        """Short provider name used in logs and usage records."""
        ...

    @property
    def model(self) -> str:
        """The model id requests are sent to."""
        ...

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Send ``request`` and return the response, or raise an `LlmError` subclass."""
        ...
