"""Errors raised by the simulated bank."""

from nexa.domain.errors import DomainError


class RecordNotFoundError(DomainError):
    """Raised when a customer, account, transaction or KYC record does not exist."""


class DuplicateRecordError(DomainError):
    """Raised when seed data contains the same id twice."""


class AccountFrozenError(DomainError):
    """Raised when a transaction is attempted on a frozen account."""


class InsufficientFundsError(DomainError):
    """Raised when a debit is larger than the account's balance."""
