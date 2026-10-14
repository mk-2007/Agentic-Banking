"""The data agent's output: typed facts about one case, plus the evidence recording them.

The facts are what the analysis agent computes on. ``merchant_name`` and ``memo`` are third-party
text and are **untrusted**: they are kept here only so code can compare and scan them, and they are
never copied into evidence or into a prompt.
"""

from collections.abc import Mapping
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field

from nexa.domain.base import Contract
from nexa.domain.evidence import Evidence, EvidenceKind


class TransactionFact(Contract):
    """One transaction as the tools report it."""

    transaction_id: str
    account_id: str
    occurred_at: AwareDatetime
    direction: Literal["debit", "credit"]
    amount: int = Field(gt=0, description="Whole PKR.")
    merchant_name: str = Field(description="Untrusted third-party text.")
    merchant_category: str
    country: str
    city: str
    channel: str
    device_trusted: bool
    is_new_beneficiary: bool
    failed_auth_attempts_prior_hour: int = Field(ge=0)
    memo: str = Field(default="", description="Untrusted third-party text.")


class TravelNoticeFact(Contract):
    """A declared trip."""

    country: str
    from_date: date
    to_date: date


class CustomerFact(Contract):
    """The risk-relevant profile of the customer."""

    customer_id: str
    risk_tier: str
    home_country: str
    home_city: str
    trusted_device_ids: tuple[str, ...] = ()
    travel_notices: tuple[TravelNoticeFact, ...] = ()


class AccountFact(Contract):
    """The state of the account."""

    account_id: str
    customer_id: str
    status: str
    card_status: str
    balance: int = Field(ge=0)


class KycFact(Contract):
    """KYC state and whether its address agrees with the customer record."""

    customer_id: str
    status: str
    missing_items: tuple[str, ...] = ()
    last_reviewed_on: date | None = None
    address_matches_customer_record: bool | None = None


class Dossier(Contract):
    """Everything the data agent gathered for one case."""

    case_id: str
    transaction: TransactionFact
    customer: CustomerFact
    account: AccountFact
    kyc: KycFact
    evidence: tuple[Evidence, ...]

    def evidence_id(self, kind: EvidenceKind) -> str | None:
        """Return the id of the evidence of ``kind``, if the dossier has it."""
        return next((e.id for e in self.evidence if e.kind is kind), None)

    def evidence_id_of(self, kind: str) -> str:
        """Return the id of the evidence of ``kind`` (a value of `EvidenceKind`).

        Raises:
            KeyError: if the dossier does not hold that kind (a built dossier always does).

        """
        found = self.evidence_id(EvidenceKind(kind))
        if found is None:
            raise KeyError(kind)
        return found


def _pick(model: type[Contract], row: Mapping[str, object]) -> dict[str, object]:
    """Keep only the keys ``model`` declares; tools return a few more (display names, flags)."""
    return {name: row[name] for name in model.model_fields if name in row}


def transaction_fact(row: Mapping[str, object]) -> TransactionFact:
    """Validate a transaction row from a tool."""
    return TransactionFact.model_validate(_pick(TransactionFact, row))


def customer_fact(row: Mapping[str, object]) -> CustomerFact:
    """Validate a customer profile from a tool."""
    return CustomerFact.model_validate(_pick(CustomerFact, row))


def account_fact(row: Mapping[str, object]) -> AccountFact:
    """Validate an account from a tool."""
    return AccountFact.model_validate(_pick(AccountFact, row))


def kyc_fact(row: Mapping[str, object]) -> KycFact:
    """Validate a KYC summary from a tool."""
    return KycFact.model_validate(_pick(KycFact, row))
