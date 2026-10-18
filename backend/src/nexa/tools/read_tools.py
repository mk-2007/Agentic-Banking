"""Read-only tools for investigators and the data/analysis agents.

Privacy by design (KB section 11): each tool returns only what an investigation needs.
Phone numbers, e-mail addresses and street addresses never leave the bank layer, and names are
reduced to initials. Free-text fields supplied by third parties are labelled as untrusted.
"""

from datetime import UTC, date, datetime
from typing import ClassVar

from pydantic import Field, field_validator

from nexa.bank_sim.models import TransactionRecord
from nexa.config import roles_for
from nexa.domain.actions import RiskLevel
from nexa.domain.base import Contract, JsonDict
from nexa.domain.tooling import ToolCall, ToolSpec

from .base import Tool, ToolContext

HISTORY_MAX_ROWS = 500


def _spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        risk_level=RiskLevel.INFORMATIONAL,
        required_roles=roles_for(name),
        read_only=True,
    )


def _initials(full_name: str) -> str:
    return " ".join(f"{part[0]}." for part in full_name.split())


def _day(value: date) -> str:
    return value.isoformat()


class _CustomerArgs(Contract):
    customer_id: str = Field(min_length=1)


class _AccountArgs(Contract):
    account_id: str = Field(min_length=1)


class _TransactionArgs(Contract):
    transaction_id: str = Field(min_length=1)


class _HistoryArgs(Contract):
    account_id: str = Field(min_length=1)
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=200, ge=1, le=HISTORY_MAX_ROWS)

    @field_validator("since", "until")
    @classmethod
    def assume_utc(cls, value: datetime | None) -> datetime | None:
        """Read a time with no zone (a bare date, say) as UTC, as the stored times are."""
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class GetCustomerProfile(Tool):
    """Return a customer's risk-relevant profile (no contact details)."""

    spec: ClassVar[ToolSpec] = _spec(
        "get_customer_profile", "Risk-relevant customer profile without contact details."
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return the profile of ``customer_id``."""
        args = _CustomerArgs.model_validate(call.arguments)
        ctx.require_scope(call, customer_id=args.customer_id)
        customer = ctx.bank.get_customer(args.customer_id)
        return {
            "customer_id": customer.id,
            "display_name": _initials(customer.full_name),
            "risk_tier": customer.risk_tier.value,
            "segment": customer.segment,
            "home_country": customer.home_country,
            "home_city": customer.home_city,
            "trusted_device_ids": list(customer.trusted_device_ids),
            "travel_notices": [
                {"country": n.country, "from_date": _day(n.from_date), "to_date": _day(n.to_date)}
                for n in customer.travel_notices
            ],
        }


class GetAccountDetails(Tool):
    """Return an account's state."""

    spec: ClassVar[ToolSpec] = _spec("get_account_details", "State of one account and its card.")

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return the account ``account_id``."""
        args = _AccountArgs.model_validate(call.arguments)
        ctx.require_scope(call, account_id=args.account_id)
        account = ctx.bank.get_account(args.account_id)
        return {
            "account_id": account.id,
            "customer_id": account.customer_id,
            "product": account.product,
            "status": account.status.value,
            "card_status": account.card_status.value,
            "balance": account.balance,
            "opened_on": _day(account.opened_on),
        }


def _transaction_row(t: TransactionRecord, *, include_memo: bool) -> JsonDict:
    row: JsonDict = {
        "transaction_id": t.id,
        "account_id": t.account_id,
        "occurred_at": t.occurred_at.isoformat(),
        "direction": t.direction.value,
        "amount": t.amount,
        "merchant_name": t.merchant_name,
        "merchant_category": t.merchant_category,
        "country": t.country,
        "city": t.city,
        "channel": t.channel.value,
        "device_trusted": t.device_trusted,
        "is_new_beneficiary": t.is_new_beneficiary,
        "failed_auth_attempts_prior_hour": t.failed_auth_attempts_prior_hour,
    }
    if include_memo:
        row["device_id"] = t.device_id
        row["counterparty_id"] = t.counterparty_id
        row["memo"] = t.memo
    return row


class GetTransactionDetails(Tool):
    """Return one transaction in full."""

    spec: ClassVar[ToolSpec] = _spec("get_transaction_details", "Full detail of one transaction.")

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return the transaction ``transaction_id``."""
        args = _TransactionArgs.model_validate(call.arguments)
        transaction = ctx.bank.get_transaction(args.transaction_id)
        ctx.require_scope(call, account_id=transaction.account_id)
        row = _transaction_row(transaction, include_memo=True)
        # Third-party free text: analysts and agents must treat it as data, never instructions.
        row["untrusted_text_fields"] = ["merchant_name", "memo"]
        return row


class GetTransactionHistory(Tool):
    """Return an account's transactions, oldest first."""

    spec: ClassVar[ToolSpec] = _spec(
        "get_transaction_history", "Transaction history of one account within an optional window."
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return up to ``limit`` of the most recent transactions in the window."""
        args = _HistoryArgs.model_validate(call.arguments)
        ctx.require_scope(call, account_id=args.account_id)
        rows = ctx.bank.list_transactions(args.account_id, since=args.since, until=args.until)
        kept = rows[-args.limit :]
        return {
            "account_id": args.account_id,
            "total_in_window": len(rows),
            "returned": len(kept),
            "truncated": len(kept) < len(rows),
            "untrusted_text_fields": ["merchant_name"],
            "transactions": [dict(_transaction_row(t, include_memo=False)) for t in kept],
        }


class GetKycStatus(Tool):
    """Return KYC state and whether its address agrees with the customer record."""

    spec: ClassVar[ToolSpec] = _spec(
        "get_kyc_status", "KYC status, missing items and address consistency (no raw addresses)."
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Return the KYC summary for ``customer_id``."""
        args = _CustomerArgs.model_validate(call.arguments)
        ctx.require_scope(call, customer_id=args.customer_id)
        kyc = ctx.bank.get_kyc(args.customer_id)
        customer = ctx.bank.get_customer(args.customer_id)
        matches: bool | None = None
        if kyc.address_on_document is not None:
            matches = customer.address.startswith(kyc.address_on_document)
        return {
            "customer_id": kyc.customer_id,
            "status": kyc.status.value,
            "missing_items": list(kyc.missing_items),
            "last_reviewed_on": _day(kyc.last_reviewed_on) if kyc.last_reviewed_on else None,
            "address_matches_customer_record": matches,
        }
