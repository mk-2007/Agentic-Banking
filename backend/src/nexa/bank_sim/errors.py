"""Errors raised by the simulated bank."""

from nexa.domain.errors import DomainError


class RecordNotFoundError(DomainError):
    """Raised when a customer, account, transaction or KYC record does not exist."""


class DuplicateRecordError(DomainError):
    """Raised when seed data contains the same id twice."""
