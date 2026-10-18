"""The customer-facing side of the bank: what a customer sees and the payments they make.

This is the app's back end, not part of the investigation. It reads the customer's own accounts and
posts their payments to the simulated bank, working out the things a bank's systems would know
(is the device registered, is the payee new) instead of trusting the customer to say. Later stages
hand each posted payment to the monitor. Nothing here touches cases, approvals or the audit log.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from nexa.bank_sim.gateway import BankGateway
from nexa.bank_sim.models import Channel, Direction, TransactionRecord
from nexa.domain.ids import new_id

from .schemas import (
    AppAccountView,
    AppMeView,
    AppTransactionView,
    PaymentRequest,
    PaymentView,
)

RECENT_ROWS = 15
NEW_PAYEE_WINDOW = timedelta(hours=24)  # a payee first paid within a day still counts as new


class NotYourAccountError(PermissionError):
    """The account belongs to someone else."""


def _initials(full_name: str) -> str:
    return " ".join(f"{part[0]}." for part in full_name.split())


class LiveService:
    """Serves the customer app from the simulated bank."""

    def __init__(self, bank: BankGateway, clock: Callable[[], datetime]) -> None:
        self._bank = bank
        self._clock = clock
        self._new_devices = 0

    def me(self, customer_id: str) -> AppMeView:
        """Return the customer's accounts and their latest transactions."""
        customer = self._bank.get_customer(customer_id)
        accounts = self._bank.list_accounts(customer_id)
        rows = sorted(
            (t for a in accounts for t in self._bank.list_transactions(a.id)),
            key=lambda t: (t.occurred_at, t.id),
            reverse=True,
        )[:RECENT_ROWS]
        return AppMeView(
            customer_id=customer.id,
            display_name=_initials(customer.full_name),
            home_country=customer.home_country,
            accounts=[
                AppAccountView(
                    id=a.id,
                    product=a.product,
                    status=a.status.value,
                    card_status=a.card_status.value,
                    balance=a.balance,
                )
                for a in accounts
            ],
            recent=[
                AppTransactionView(
                    id=t.id,
                    account_id=t.account_id,
                    occurred_at=t.occurred_at,
                    direction=t.direction.value,
                    amount=t.amount,
                    merchant_name=t.merchant_name,
                    merchant_category=t.merchant_category,
                    country=t.country,
                    channel=t.channel.value,
                )
                for t in rows
            ],
        )

    def pay(
        self, customer_id: str, request: PaymentRequest
    ) -> tuple[TransactionRecord, PaymentView]:
        """Post a payment from the customer's own account and return it with the bank's answer.

        Raises `NotYourAccountError`, `RecordNotFoundError`, `AccountFrozenError` or
        `InsufficientFundsError`.
        """
        account = self._bank.get_account(request.account_id)
        if account.customer_id != customer_id:
            raise NotYourAccountError(request.account_id)
        customer = self._bank.get_customer(customer_id)
        now = self._clock()

        if request.device == "registered" and customer.trusted_device_ids:
            device_id, trusted = customer.trusted_device_ids[0], True
        else:
            self._new_devices += 1
            device_id, trusted = f"dev_new_{customer_id}_{self._new_devices}", False

        counterparty: str | None = None
        new_payee = False
        if request.merchant_category == "transfer":  # a payee exists whatever the channel
            counterparty = request.payee_account or f"name:{request.merchant_name.casefold()}"
            earlier = self._bank.list_transactions(account.id, until=now - NEW_PAYEE_WINDOW)
            new_payee = not any(t.counterparty_id == counterparty for t in earlier)

        record = TransactionRecord(
            id=new_id("txn"),
            account_id=account.id,
            occurred_at=now,
            direction=Direction.DEBIT,
            amount=request.amount,
            merchant_name=request.merchant_name,
            merchant_category=request.merchant_category,
            country=request.country.upper(),
            city=request.city,
            channel=Channel(request.channel),
            device_id=device_id,
            device_trusted=trusted,
            counterparty_id=counterparty,
            is_new_beneficiary=new_payee,
            failed_auth_attempts_prior_hour=request.failed_logins,
        )
        self._bank.add_transaction(record)
        after = self._bank.get_account(account.id)
        return record, PaymentView(
            transaction_id=record.id,
            balance_after=after.balance,
            account_status=after.status.value,
        )
