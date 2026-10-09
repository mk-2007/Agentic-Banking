"""Domain-level exceptions."""


class DomainError(Exception):
    """Base class for errors raised by domain rules."""


class InvalidTransitionError(DomainError):
    """Raised when a case is moved to a status its current status does not allow."""
