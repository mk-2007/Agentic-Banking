"""Analysis agent: turns a dossier and the account history into typed findings.

The arithmetic is plain code, because thresholds are policy (NB-POL-FRAUD-001, NB-POL-AML-001)
and must give the same answer every time. The agent fetches the history through its own tool
permission, compares the case with the customer's *earlier* behaviour, and returns findings that a
verification step can recompute. No model is involved, and no third-party text is copied into a
finding (instruction-like text is only counted, never quoted).
"""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from nexa.config import FraudThresholds
from nexa.domain.actors import Role
from nexa.domain.case import Case
from nexa.domain.evidence import Evidence, SourceRef

from .base import AgentContext, ToolSession
from .dossier import Dossier, TransactionFact, transaction_fact
from .findings import IndicatorCode, finding_evidence

DIGITAL_CHANNELS = frozenset({"web", "mobile_app", "card_online"})
TRANSFER_CATEGORY = "transfer"
HISTORY_ROWS = 500  # the most the history tool returns in one call

# Text in third-party fields that tries to direct the investigation (NB-POL-FRAUD-001 section 6).
# A heuristic: it finds the obvious attempts, and its limits are listed in docs/agents.md.
_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|rules)",
        r"\b(system|admin(istrator)?)\s+(notice|message|override)\b",
        r"\bto\s+(ai|llm)\s+(agents?|assistants?)\b",
        r"\b(approve|authori[sz]e)\s+(it|this|the)\b",
        r"\b(freeze|block|unblock|release)\s+(the\s+)?(account|card)\b",
        r"\bdo\s+not\s+(flag|report|escalate)\b",
        r"\bdisregard\b",
    )
)


def _instruction_hits(text: str) -> int:
    """Return how many distinct instruction-like patterns appear in ``text``."""
    return sum(1 for pattern in _INSTRUCTION_PATTERNS if pattern.search(text))


class AnalysisAgent:
    """Compares one transaction with the customer's own history and KYC state."""

    role = Role.ANALYSIS_AGENT

    def __init__(self, ctx: AgentContext) -> None:
        self._ctx = ctx

    def analyze(self, case: Case, dossier: Dossier) -> tuple[Evidence, ...]:
        """Fetch the account history and return the findings for ``case``."""
        thresholds = self._ctx.thresholds
        session = ToolSession(self._ctx, self.role, case.id)
        since = dossier.transaction.occurred_at - timedelta(days=thresholds.history_lookback_days)
        output = session.call(
            "get_transaction_history",
            {
                "account_id": case.alert.account_id,
                "since": since.isoformat(),
                "limit": HISTORY_ROWS,
            },
        )
        rows = output.get("transactions")
        history = (
            tuple(transaction_fact(row) for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else ()
        )
        return derive_findings(dossier, history, thresholds, self._ctx.clock())


def derive_findings(
    dossier: Dossier,
    history: Sequence[TransactionFact],
    thresholds: FraudThresholds,
    collected_at: datetime,
) -> tuple[Evidence, ...]:
    """Compute every finding that applies to ``dossier``. Pure: no tools, no clock, no model.

    Behaviour is judged against the history *before* the velocity window that ends at the alerted
    transaction, so a burst of suspicious payments cannot make itself look normal.
    """
    t = thresholds
    alert = dossier.transaction
    case_id = dossier.case_id
    txn_ev = dossier.evidence_id_of("transaction")
    kyc_ev = dossier.evidence_id_of("kyc_status")
    customer_ev = dossier.evidence_id_of("customer_profile")

    window_start = alert.occurred_at - timedelta(minutes=t.velocity_window_minutes)
    lookback_start = alert.occurred_at - timedelta(days=t.history_lookback_days)
    prior = [
        h
        for h in history
        if h.transaction_id != alert.transaction_id
        and lookback_start <= h.occurred_at < alert.occurred_at
    ]
    burst = [h for h in prior if h.occurred_at >= window_start] + [alert]
    baseline = [h for h in prior if h.occurred_at < window_start and h.direction == "debit"]
    thin_history = len(prior) < t.min_history_transactions

    txn_source = SourceRef(tool_name="get_transaction_history", record_id=alert.transaction_id)
    kyc_source = SourceRef(tool_name="get_kyc_status", record_id=dossier.kyc.customer_id)
    profile_source = SourceRef(
        tool_name="get_customer_profile", record_id=dossier.customer.customer_id
    )
    details_source = SourceRef(tool_name="get_transaction_details", record_id=alert.transaction_id)

    findings: list[Evidence] = []

    def add(
        code: IndicatorCode,
        summary: str,
        source: SourceRef,
        derived: tuple[str, ...],
        values: dict[str, str | int | float | bool | None] | None = None,
        detail: str | None = None,
    ) -> None:
        findings.append(
            finding_evidence(
                case_id, code, summary, derived_from=derived, source=source,
                collected_at=collected_at, values=values, detail=detail,
            )
        )  # fmt: skip

    # --- amount ------------------------------------------------------------
    average = round(sum(h.amount for h in baseline) / len(baseline), 2) if baseline else None
    if thin_history:
        add(
            IndicatorCode.INSUFFICIENT_HISTORY,
            f"only {len(prior)} transactions in the last {t.history_lookback_days} days; "
            f"behaviour cannot be judged reliably",
            txn_source, (txn_ev,),
            {"transactions_in_lookback": len(prior), "required": t.min_history_transactions},
        )  # fmt: skip
    elif alert.direction == "debit" and average is not None:
        multiple = alert.amount / average
        if alert.amount >= t.amount_multiple_of_average * average:
            add(
                IndicatorCode.AMOUNT_ABOVE_AVERAGE,
                f"payment of PKR {alert.amount:,} is {multiple:.1f} times the customer's average "
                f"of PKR {average:,.0f} over {len(baseline)} earlier payments",
                txn_source, (txn_ev,),
                {"amount": alert.amount, "baseline_average": average,
                 "baseline_payments": len(baseline), "multiple": round(multiple, 1)},
            )  # fmt: skip
        else:
            add(
                IndicatorCode.WITHIN_NORMAL_RANGE,
                f"payment of PKR {alert.amount:,} is {multiple:.1f} times the customer's average",
                txn_source, (txn_ev,),
                {"amount": alert.amount, "baseline_average": average,
                 "multiple": round(multiple, 1)},
            )  # fmt: skip
    if alert.amount >= t.high_value_amount_pkr:
        add(
            IndicatorCode.HIGH_VALUE,
            f"single {alert.direction} of PKR {alert.amount:,} is at or above "
            f"PKR {t.high_value_amount_pkr:,}",
            txn_source, (txn_ev,),
            {"amount": alert.amount, "threshold": t.high_value_amount_pkr},
        )  # fmt: skip

    # --- bursts ------------------------------------------------------------
    payments = [h for h in burst if h.direction == "debit"]
    small_limit = alert.amount * t.card_testing_max_fraction_of_alert
    small_by_merchant = Counter(
        h.merchant_name for h in payments
        if h.transaction_id != alert.transaction_id and h.amount <= small_limit
    )  # fmt: skip
    small_count = max(small_by_merchant.values(), default=0)
    testing = alert.direction == "debit" and small_count >= t.card_testing_min_payments
    if testing:
        add(
            IndicatorCode.CARD_TESTING,
            f"{small_count} very small payments to one merchant, then a payment of "
            f"PKR {alert.amount:,}, within {t.velocity_window_minutes} minutes",
            txn_source, (txn_ev,),
            {"small_payments": small_count, "max_small_amount": int(small_limit),
             "alert_amount": alert.amount, "window_minutes": t.velocity_window_minutes},
        )  # fmt: skip
    elif len(payments) >= t.velocity_transaction_count:
        transfers = sum(1 for h in payments if h.merchant_category == TRANSFER_CATEGORY)
        add(
            IndicatorCode.RAPID_SERIES,
            f"{len(payments)} payments ({transfers} transfers) within "
            f"{t.velocity_window_minutes} minutes",
            txn_source, (txn_ev,),
            {"payments": len(payments), "transfers": transfers,
             "window_minutes": t.velocity_window_minutes,
             "total_amount": sum(h.amount for h in payments)},
        )  # fmt: skip

    worst_failed = max(h.failed_auth_attempts_prior_hour for h in burst)
    if worst_failed >= t.failed_auth_attempts:
        add(
            IndicatorCode.FAILED_AUTH,
            f"{worst_failed} failed authentication attempts in the hour before a payment",
            txn_source, (txn_ev,),
            {"max_failed_attempts": worst_failed, "threshold": t.failed_auth_attempts},
        )  # fmt: skip
    new_beneficiary = sum(1 for h in burst if h.is_new_beneficiary)
    if new_beneficiary:
        add(
            IndicatorCode.NEW_BENEFICIARY,
            f"{new_beneficiary} payment(s) in the window went to a recently added beneficiary",
            txn_source, (txn_ev,),
            {"payments_to_new_beneficiaries": new_beneficiary},
        )  # fmt: skip
    unknown_device = sum(1 for h in burst if h.channel in DIGITAL_CHANNELS and not h.device_trusted)
    if unknown_device:
        add(
            IndicatorCode.UNKNOWN_DEVICE,
            f"{unknown_device} online payment(s) in the window came from an unregistered device",
            txn_source, (txn_ev,),
            {"untrusted_device_payments": unknown_device},
        )  # fmt: skip

    # --- geography, device and merchant -----------------------------------
    home = dossier.customer.home_country
    if alert.country != home:
        day = alert.occurred_at.date()
        covered = any(
            n.country == alert.country and n.from_date <= day <= n.to_date
            for n in dossier.customer.travel_notices
        )
        geography_ids = (txn_ev, customer_ev)
        if covered:
            add(
                IndicatorCode.TRAVEL_NOTICE,
                f"activity in {alert.country} is covered by the customer's travel notice",
                profile_source, geography_ids,
                {"country": alert.country, "home_country": home},
            )  # fmt: skip
        else:
            seen_before = any(h.country == alert.country for h in prior)
            add(
                IndicatorCode.UNUSUAL_GEOGRAPHY,
                f"activity in {alert.country} (home country {home}) with no travel notice"
                + ("" if seen_before else "; this country has no earlier activity"),
                profile_source, geography_ids,
                {"country": alert.country, "home_country": home, "seen_before": seen_before},
            )  # fmt: skip
    if alert.device_trusted:
        add(
            IndicatorCode.TRUSTED_DEVICE,
            "the transaction came from a device registered to the customer",
            details_source, (txn_ev,),
            {"channel": alert.channel},
        )  # fmt: skip
    if not thin_history and any(
        h.merchant_name.casefold() == alert.merchant_name.casefold()
        for h in prior
        if h.occurred_at < window_start
    ):
        add(
            IndicatorCode.FAMILIAR_MERCHANT,
            "the customer has paid this merchant before",
            txn_source, (txn_ev,),
        )  # fmt: skip

    # --- KYC -----------------------------------------------------------------
    kyc = dossier.kyc
    if kyc.status != "verified":
        add(
            IndicatorCode.KYC_NOT_VERIFIED,
            f"KYC status is {kyc.status}",
            kyc_source, (kyc_ev,), {"status": kyc.status},
        )  # fmt: skip
    for item in kyc.missing_items:
        add(
            IndicatorCode.KYC_ITEM_MISSING,
            f"KYC item missing: {item}",
            kyc_source, (kyc_ev,), {"item": item}, detail=item,
        )  # fmt: skip
    if kyc.address_matches_customer_record is False:
        add(
            IndicatorCode.KYC_ADDRESS_MISMATCH,
            "the address on the KYC document differs from the customer record",
            kyc_source, (kyc_ev,),
        )  # fmt: skip
    if kyc.last_reviewed_on is not None:
        age = (alert.occurred_at.date() - kyc.last_reviewed_on).days
        if age > t.kyc_review_max_age_days:
            add(
                IndicatorCode.KYC_REVIEW_OVERDUE,
                f"KYC was last reviewed {age} days ago (limit {t.kyc_review_max_age_days})",
                kyc_source, (kyc_ev,),
                {"days_since_review": age, "limit_days": t.kyc_review_max_age_days},
            )  # fmt: skip

    # --- untrusted text --------------------------------------------------------
    hits = {
        "memo": _instruction_hits(alert.memo),
        "merchant_name": _instruction_hits(alert.merchant_name),
    }
    field = max(hits, key=lambda name: hits[name])
    if hits[field]:
        add(
            IndicatorCode.INSTRUCTION_TEXT,
            f"text in the {field} field tries to direct the investigation; treated as data",
            details_source, (txn_ev,),
            {"field": field, "patterns_matched": hits[field]},
        )  # fmt: skip
    return tuple(findings)
