"""In-memory simulated bank implementing `BankGateway`.

Holds validated records in dictionaries. Records are immutable, so an action such as
freezing an account replaces the stored record with an updated copy.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import TypeVar

from .errors import DuplicateRecordError, RecordNotFoundError
from .models import (
    AccountRecord,
    AccountStatus,
    CardStatus,
    CustomerRecord,
    KycRecord,
    TransactionRecord,
)

_T = TypeVar("_T")


def _index(items: Iterable[_T], key: str, kind: str) -> dict[str, _T]:
    """Index ``items`` by attribute ``key``, rejecting duplicate ids."""
    indexed: dict[str, _T] = {}
    for item in items:
        item_id = getattr(item, key)
        if item_id in indexed:
            raise DuplicateRecordError(f"duplicate {kind} id: {item_id}")
        indexed[item_id] = item
    return indexed


class InMemoryBank:
    """A small, deterministic stand-in for a bank's core systems."""

    def __init__(
        self,
        customers: Iterable[CustomerRecord],
        accounts: Iterable[AccountRecord],
        transactions: Iterable[TransactionRecord],
        kyc: Iterable[KycRecord],
    ) -> None:
        self._customers = _index(customers, "id", "customer")
        self._accounts = _index(accounts, "id", "account")
        self._transactions = _index(transactions, "id", "transaction")
        self._kyc = _index(kyc, "customer_id", "kyc")

    # --- CustomerAPI -------------------------------------------------
    def get_customer(self, customer_id: str) -> CustomerRecord:
        """Return the customer or raise RecordNotFoundError."""
        return self._lookup(self._customers, customer_id, "customer")

    # --- AccountAPI --------------------------------------------------
    def get_account(self, account_id: str) -> AccountRecord:
        """Return the account or raise RecordNotFoundError."""
        return self._lookup(self._accounts, account_id, "account")

    def list_accounts(self, customer_id: str) -> tuple[AccountRecord, ...]:
        """Return every account owned by the customer (possibly none)."""
        return tuple(a for a in self._accounts.values() if a.customer_id == customer_id)

    # --- TransactionAPI ----------------------------------------------
    def get_transaction(self, transaction_id: str) -> TransactionRecord:
        """Return the transaction or raise RecordNotFoundError."""
        return self._lookup(self._transactions, transaction_id, "transaction")

    def list_transactions(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[TransactionRecord, ...]:
        """Return the account's transactions, oldest first, within ``[since, until]``."""
        self.get_account(account_id)  # unknown accounts are an error, empty history is not
        selected = [
            t
            for t in self._transactions.values()
            if t.account_id == account_id
            and (since is None or t.occurred_at >= since)
            and (until is None or t.occurred_at <= until)
        ]
        return tuple(sorted(selected, key=lambda t: (t.occurred_at, t.id)))

    # --- KycAPI ------------------------------------------------------
    def get_kyc(self, customer_id: str) -> KycRecord:
        """Return the KYC record or raise RecordNotFoundError."""
        return self._lookup(self._kyc, customer_id, "kyc record for customer")

    # --- AccountActionAPI --------------------------------------------
    def freeze_account(self, account_id: str) -> AccountRecord:
        """Freeze the account (idempotent) and return the updated record."""
        updated = self.get_account(account_id).model_copy(update={"status": AccountStatus.FROZEN})
        self._accounts[account_id] = updated
        return updated

    def block_card(self, account_id: str) -> AccountRecord:
        """Block the account's card (idempotent) and return the updated record."""
        updated = self.get_account(account_id).model_copy(
            update={"card_status": CardStatus.BLOCKED}
        )
        self._accounts[account_id] = updated
        return updated

    @staticmethod
    def _lookup(store: dict[str, _T], key: str, kind: str) -> _T:
        try:
            return store[key]
        except KeyError:
            raise RecordNotFoundError(f"{kind} not found: {key}") from None
