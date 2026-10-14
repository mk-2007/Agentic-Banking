"""Data agent: fetches the records of one case through tools and records them as evidence.

It does no analysis. Its job is to turn tool output into validated facts and traceable evidence
(PRD section 10.2). Evidence summaries are built from numbers and categories only, so merchant
names and memos (untrusted text) never leave the dossier.
"""

from collections.abc import Mapping

from nexa.domain.actors import Role
from nexa.domain.case import Case
from nexa.domain.errors import DomainError
from nexa.domain.evidence import Evidence, EvidenceKind, SourceRef

from .base import AgentContext, ToolSession
from .dossier import (
    Dossier,
    account_fact,
    customer_fact,
    kyc_fact,
    transaction_fact,
)


class AgentDataError(DomainError):
    """The records a tool returned do not belong together, so the case cannot be trusted."""


class DataAgent:
    """Gathers the transaction, customer, account and KYC records for a case."""

    role = Role.DATA_AGENT

    def __init__(self, ctx: AgentContext) -> None:
        self._ctx = ctx

    def gather(self, case: Case) -> Dossier:
        """Return the dossier for ``case``, or raise `AgentToolError` / `AgentDataError`."""
        alert = case.alert
        session = ToolSession(self._ctx, self.role, case.id)
        txn_row = session.call("get_transaction_details", {"transaction_id": alert.transaction_id})
        customer_row = session.call("get_customer_profile", {"customer_id": alert.customer_id})
        account_row = session.call("get_account_details", {"account_id": alert.account_id})
        kyc_row = session.call("get_kyc_status", {"customer_id": alert.customer_id})

        transaction = transaction_fact(txn_row)
        customer = customer_fact(customer_row)
        account = account_fact(account_row)
        kyc = kyc_fact(kyc_row)
        if transaction.account_id != alert.account_id or account.account_id != alert.account_id:
            raise AgentDataError("the transaction or account does not match the alert")
        if account.customer_id != alert.customer_id or customer.customer_id != alert.customer_id:
            raise AgentDataError("the account or customer does not match the alert")

        evidence = (
            self._evidence(
                case.id, EvidenceKind.TRANSACTION, "get_transaction_details",
                transaction.transaction_id,
                f"{transaction.direction} of PKR {transaction.amount:,} "
                f"({transaction.merchant_category}, {transaction.country}, {transaction.channel})",
                {
                    "transaction_id": transaction.transaction_id,
                    "occurred_at": transaction.occurred_at.isoformat(),
                    "direction": transaction.direction,
                    "amount": transaction.amount,
                    "merchant_category": transaction.merchant_category,
                    "country": transaction.country,
                    "channel": transaction.channel,
                    "device_trusted": transaction.device_trusted,
                    "is_new_beneficiary": transaction.is_new_beneficiary,
                    "failed_auth_attempts_prior_hour": transaction.failed_auth_attempts_prior_hour,
                },
            ),
            self._evidence(
                case.id, EvidenceKind.CUSTOMER_PROFILE, "get_customer_profile",
                customer.customer_id,
                f"customer in the {customer.risk_tier} risk tier, "
                f"home country {customer.home_country}",
                {
                    "customer_id": customer.customer_id,
                    "risk_tier": customer.risk_tier,
                    "home_country": customer.home_country,
                    "trusted_device_count": len(customer.trusted_device_ids),
                    "travel_notice_count": len(customer.travel_notices),
                },
            ),
            self._evidence(
                case.id, EvidenceKind.ACCOUNT_STATE, "get_account_details", account.account_id,
                f"account is {account.status}, card is {account.card_status}",
                {
                    "account_id": account.account_id,
                    "status": account.status,
                    "card_status": account.card_status,
                    "balance": account.balance,
                },
            ),
            self._evidence(
                case.id, EvidenceKind.KYC_STATUS, "get_kyc_status", kyc.customer_id,
                f"KYC is {kyc.status}"
                + (f", missing: {', '.join(kyc.missing_items)}" if kyc.missing_items else ""),
                {
                    "customer_id": kyc.customer_id,
                    "status": kyc.status,
                    "missing_items": ",".join(kyc.missing_items),
                    "address_matches_customer_record": kyc.address_matches_customer_record,
                    "last_reviewed_on": kyc.last_reviewed_on.isoformat()
                    if kyc.last_reviewed_on
                    else None,
                },
            ),
        )  # fmt: skip
        return Dossier(
            case_id=case.id,
            transaction=transaction,
            customer=customer,
            account=account,
            kyc=kyc,
            evidence=evidence,
        )

    def _evidence(
        self,
        case_id: str,
        kind: EvidenceKind,
        tool_name: str,
        record_id: str,
        summary: str,
        data: Mapping[str, str | int | float | bool | None],
    ) -> Evidence:
        return Evidence(
            id=f"ev_{case_id}_{kind.value}",
            case_id=case_id,
            kind=kind,
            summary=summary,
            data=dict(data),
            source=SourceRef(tool_name=tool_name, record_id=record_id),
            collected_at=self._ctx.clock(),
        )
