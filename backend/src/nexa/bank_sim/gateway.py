"""Interfaces a real bank integration would implement.

The PRD (section 17) asks for simulated APIs that mirror real banking APIs. These
`Protocol` classes are that contract. The tool layer depends on them, never on the
in-memory implementation, so replacing the simulator with a real gateway changes nothing above it.

Read APIs are safe to expose to many roles. `AccountActionAPI` changes state: only the
tool layer may call it, and only with an approved, unexpired approval.
"""

from datetime import datetime
from typing import Protocol

from .models import AccountRecord, CustomerRecord, KycRecord, TransactionRecord


class CustomerAPI(Protocol):
    """Read access to customer profiles."""

    def get_customer(self, customer_id: str) -> CustomerRecord:
        """Return the customer or raise RecordNotFoundError."""
        ...


class AccountAPI(Protocol):
    """Read access to accounts."""

    def get_account(self, account_id: str) -> AccountRecord:
        """Return the account or raise RecordNotFoundError."""
        ...

    def list_accounts(self, customer_id: str) -> tuple[AccountRecord, ...]:
        """Return every account owned by the customer (possibly none)."""
        ...


class TransactionAPI(Protocol):
    """Read access to transaction history."""

    def get_transaction(self, transaction_id: str) -> TransactionRecord:
        """Return the transaction or raise RecordNotFoundError."""
        ...

    def list_transactions(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[TransactionRecord, ...]:
        """Return the account's transactions, oldest first, within ``[since, until]``."""
        ...


class KycAPI(Protocol):
    """Read access to KYC records."""

    def get_kyc(self, customer_id: str) -> KycRecord:
        """Return the KYC record or raise RecordNotFoundError."""
        ...


class AccountActionAPI(Protocol):
    """State-changing operations. Callable only through the authorized tool layer."""

    def freeze_account(self, account_id: str) -> AccountRecord:
        """Freeze the account (idempotent) and return the updated record."""
        ...

    def block_card(self, account_id: str) -> AccountRecord:
        """Block the account's card (idempotent) and return the updated record."""
        ...


class BankGateway(CustomerAPI, AccountAPI, TransactionAPI, KycAPI, AccountActionAPI, Protocol):
    """Everything the platform may ask of a bank."""
