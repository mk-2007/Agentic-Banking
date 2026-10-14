"""Small builders for analysis tests: a dossier and a history we fully control."""

from datetime import UTC, date, datetime, timedelta

from nexa.agents.dossier import (
    AccountFact,
    CustomerFact,
    Dossier,
    KycFact,
    TransactionFact,
    TravelNoticeFact,
)
from nexa.domain.evidence import Evidence, EvidenceKind, SourceRef

ALERT_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def txn(
    txn_id: str = "t_alert",
    *,
    minutes_before: int = 0,
    days_before: int = 0,
    amount: int = 1_000,
    direction: str = "debit",
    merchant: str = "Corner Shop",
    category: str = "retail",
    country: str = "PK",
    channel: str = "pos",
    trusted: bool = False,
    new_beneficiary: bool = False,
    failed: int = 0,
    memo: str = "",
) -> TransactionFact:
    return TransactionFact(
        transaction_id=txn_id, account_id="acc_1",
        occurred_at=ALERT_AT - timedelta(minutes=minutes_before, days=days_before),
        direction=direction, amount=amount, merchant_name=merchant,  # type: ignore[arg-type]
        merchant_category=category, country=country, city="X", channel=channel,
        device_trusted=trusted, is_new_beneficiary=new_beneficiary,
        failed_auth_attempts_prior_hour=failed, memo=memo,
    )  # fmt: skip


def calm_history(
    count: int = 20, amount: int = 1_000, merchant: str = "Corner Shop"
) -> list[TransactionFact]:
    """Ordinary spending, one payment a day, long before the alert window."""
    return [txn(f"h{i}", days_before=i + 1, amount=amount, merchant=merchant) for i in range(count)]


def dossier(
    alert: TransactionFact,
    *,
    kyc: KycFact | None = None,
    notices: tuple[TravelNoticeFact, ...] = (),
) -> Dossier:
    case_id = "case_1"
    source = SourceRef(tool_name="get_transaction_details", record_id=alert.transaction_id)
    evidence = tuple(
        Evidence(
            id=f"ev_{case_id}_{kind.value}", case_id=case_id, kind=kind, summary="x",
            source=source, collected_at=ALERT_AT,
        )
        for kind in (
            EvidenceKind.TRANSACTION, EvidenceKind.CUSTOMER_PROFILE,
            EvidenceKind.ACCOUNT_STATE, EvidenceKind.KYC_STATUS,
        )
    )  # fmt: skip
    return Dossier(
        case_id=case_id,
        transaction=alert,
        customer=CustomerFact(
            customer_id="c1", risk_tier="low", home_country="PK", home_city="Karachi",
            travel_notices=notices,
        ),
        account=AccountFact(
            account_id="acc_1", customer_id="c1", status="active", card_status="active", balance=1
        ),
        kyc=kyc or KycFact(customer_id="c1", status="verified", last_reviewed_on=date(2026, 6, 1)),
        evidence=evidence,
    )  # fmt: skip
