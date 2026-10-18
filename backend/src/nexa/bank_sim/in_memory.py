"""In-memory simulated bank implementing `BankGateway`.

Holds validated records in dictionaries. Records are immutable, so an action such as
freezing an account replaces the stored record with an updated copy.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import TypeVar

from .errors import (
    AccountFrozenError,
    DuplicateRecordError,
    InsufficientFundsError,
    RecordNotFoundError,
)
from .models import (
    AccountRecord,
    AccountStatus,
    CardStatus,
    CustomerRecord,
    Direction,
    KycRecord,
    OutboxEntry,
    OutboxKind,
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
        self._outbox: list[OutboxEntry] = []

    # --- CustomerAPI -------------------------------------------------
    def get_customer(self, customer_id: str) -> CustomerRecord:
        """Return the customer or raise RecordNotFoundError."""
        return self._lookup(self._customers, customer_id, "customer")

    # --- AccountAPI --------------------------------------------------
    def get_account(self, account_id: str) -> AccountRecord:
        """Return the account or raise RecordNotFoundError."""
        return self._lookup(self._accounts, account_id, "account")

    def all_accounts(self) -> tuple[AccountRecord, ...]:
        """Every account in the bank, for admin browsing (not part of the gateway protocol)."""
        return tuple(self._accounts.values())

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

    # --- TransactionWriteAPI -----------------------------------------
    def add_transaction(self, transaction: TransactionRecord) -> TransactionRecord:
        """Post the transaction and move the balance; refuse a frozen account or an overdraft."""
        account = self.get_account(transaction.account_id)
        if transaction.id in self._transactions:
            raise DuplicateRecordError(f"duplicate transaction id: {transaction.id}")
        if account.status is AccountStatus.FROZEN:
            raise AccountFrozenError(f"account {account.id} is frozen")
        signed = (
            transaction.amount if transaction.direction is Direction.CREDIT else -transaction.amount
        )
        if account.balance + signed < 0:
            raise InsufficientFundsError(f"account {account.id} has too little balance")
        self._transactions[transaction.id] = transaction
        self._accounts[account.id] = account.model_copy(
            update={"balance": account.balance + signed}
        )
        return transaction

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

    def queue_followup(
        self, account_id: str, kind: OutboxKind, case_id: str, at: datetime
    ) -> OutboxEntry:
        """Queue a follow-up for the account's operations desk and return it."""
        account = self.get_account(account_id)
        entry = OutboxEntry(
            id=f"out_{len(self._outbox) + 1:05d}",
            account_id=account_id,
            customer_id=account.customer_id,
            kind=kind,
            case_id=case_id,
            created_at=at,
        )
        self._outbox.append(entry)
        return entry

    def followups(self, account_id: str) -> tuple[OutboxEntry, ...]:
        """Return the follow-ups queued for the account, oldest first."""
        return tuple(e for e in self._outbox if e.account_id == account_id)

    @staticmethod
    def _lookup(store: dict[str, _T], key: str, kind: str) -> _T:
        try:
            return store[key]
        except KeyError:
            raise RecordNotFoundError(f"{kind} not found: {key}") from None
