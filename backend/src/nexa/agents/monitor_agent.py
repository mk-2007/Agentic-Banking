"""The monitor: decides, for each new transaction, whether an investigation case should be opened.

A bank cannot investigate every payment, and it must not miss the ones that matter. The monitor
splits the work three ways, and only the middle one is a model's call:

- **floor** (plain code): a payment that crosses a policy threshold always opens a case. A model
  can never clear one of these.
- **routine** (plain code): a payment that is ordinary in every respect is cleared without a model.
  The rule is deliberately narrow, so anything unusual falls through to the model.
- **grey zone** (a model): everything else. The model reads a typed digest of numbers and flags,
  never a merchant name or a memo, and says open or clear with a reason from a closed list. If it
  is missing, down or answers badly the monitor opens the case: failing toward caution.

The digest is built by the caller from the bank's records (agents never touch the bank).
"""

from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import Field, model_validator

from nexa.config import FraudThresholds
from nexa.domain.base import Contract
from nexa.llm import ChatMessage, LlmError, LlmGateway, LlmRequest
from nexa.llm import Role as ChatRole

ROUTINE_MAX_RATIO = 2.0  # an amount up to twice the customer's usual is ordinary
DIGITAL: Final = frozenset({"web", "mobile_app", "card_online"})
# Reasoning models spend hidden tokens before the JSON; a small cap cuts the answer off mid-object.
MAX_ANSWER_TOKENS = 1500


class TransactionDigest(Contract):
    """What the monitor knows about one new transaction: numbers and flags, no free text."""

    transaction_id: str
    direction: Literal["debit", "credit"]
    channel: str
    amount: int = Field(gt=0)
    prior_transactions: int = Field(ge=0, description="Earlier transactions in the look-back.")
    ratio_to_average: float | None = Field(
        default=None,
        description="Amount over the customer's usual payment; None if too little history.",
    )
    payments_last_hour: int = Field(ge=1, description="Including this one.")
    payments_last_day: int = Field(ge=1)
    total_last_day: int = Field(ge=1)
    near_line_last_day: int = Field(
        ge=0,
        description="Payments in the last day, same direction, just under the high-value line.",
    )
    new_payee: bool
    device_trusted: bool
    failed_logins: int = Field(ge=0)
    abroad: bool
    travel_notice_covers: bool
    country_seen_before: bool
    merchant_seen_before: bool
    share_of_balance: float = Field(ge=0.0)


class FloorReason(StrEnum):
    """Why a payment always opens a case."""

    HIGH_VALUE = "high_value"
    AMOUNT_ABOVE_AVERAGE = "amount_above_average"
    RAPID_PAYMENTS = "rapid_payments"
    FAILED_LOGINS = "failed_logins"
    NEW_PAYEE_ON_UNKNOWN_DEVICE = "new_payee_on_unknown_device"


class TriageReason(StrEnum):
    """The reasons a model may give, a closed list."""

    UNUSUAL_AMOUNT = "unusual_amount"
    UNUSUAL_PATTERN = "unusual_pattern"
    NEW_PAYEE_RISK = "new_payee_risk"
    NEAR_THRESHOLD_CLUSTER = "near_threshold_cluster"
    LOCATION_CONCERN = "location_concern"
    DEVICE_OR_LOGIN_CONCERN = "device_or_login_concern"
    NOTHING_UNUSUAL = "nothing_unusual"


def floor_reasons(d: TransactionDigest, t: FraudThresholds) -> tuple[FloorReason, ...]:
    """Return why ``d`` must open a case regardless of any model, or ``()``."""
    reasons: list[FloorReason] = []
    if d.amount >= t.high_value_amount_pkr:
        reasons.append(FloorReason.HIGH_VALUE)
    if d.ratio_to_average is not None and d.ratio_to_average >= t.amount_multiple_of_average:
        reasons.append(FloorReason.AMOUNT_ABOVE_AVERAGE)
    if d.payments_last_hour >= t.velocity_transaction_count:
        reasons.append(FloorReason.RAPID_PAYMENTS)
    if d.failed_logins >= t.failed_auth_attempts:
        reasons.append(FloorReason.FAILED_LOGINS)
    if d.new_payee and not d.device_trusted:
        reasons.append(FloorReason.NEW_PAYEE_ON_UNKNOWN_DEVICE)
    return tuple(reasons)


def is_routine(d: TransactionDigest, t: FraudThresholds) -> bool:
    """Return whether ``d`` is ordinary in every respect (and so needs no model or case)."""
    return (
        not floor_reasons(d, t)
        and d.prior_transactions >= t.min_history_transactions
        and d.ratio_to_average is not None
        and d.ratio_to_average <= ROUTINE_MAX_RATIO
        and d.amount < t.high_value_amount_pkr / 2
        and d.failed_logins == 0
        and not d.new_payee
        and (d.device_trusted or d.channel not in DIGITAL)
        and (not d.abroad or d.travel_notice_covers)
        and d.payments_last_hour <= 2
        and d.near_line_last_day <= 1
    )


class Triage(Contract):
    """The model's answer for a grey-zone payment."""

    open_case: bool
    reason: TriageReason

    @model_validator(mode="after")
    def check_reason(self) -> Self:
        """Require a real reason to open a case, and 'nothing unusual' to clear one."""
        if self.open_case == (self.reason is TriageReason.NOTHING_UNUSUAL):
            raise ValueError("open with a concern, or clear with nothing_unusual")
        return self


SYSTEM_PROMPT = (
    "You triage new transactions at a bank. For one transaction, decide whether a fraud analyst "
    "should investigate it. You see only numbers and flags about the transaction and the "
    "customer's own recent behaviour; you never see merchant names or notes. Open a case when the "
    "combination looks unusual for this customer, including payments that sit just under the "
    "PKR {high:,} high-value line in a cluster, or a new payee together with other signs. Clear it "
    "when it looks ordinary. When unsure, open. Reply with one JSON object: "
    '{{"open_case": true or false, "reason": one of {reasons}}}.'
)


class MonitorAgent:
    """Asks a model about the payments that are neither clearly routine nor clearly alarming."""

    def __init__(self, gateway: LlmGateway | None, thresholds: FraudThresholds) -> None:
        self._gateway = gateway
        self._thresholds = thresholds

    def triage(self, d: TransactionDigest) -> Triage | None:
        """Return the model's decision, or None if no model is available or it answered badly."""
        if self._gateway is None:
            return None
        system = SYSTEM_PROMPT.format(
            high=self._thresholds.high_value_amount_pkr,
            reasons=", ".join(r.value for r in TriageReason),
        )
        facts = "\n".join(f"{name}={value}" for name, value in d.model_dump().items())
        request = LlmRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content=system),
                ChatMessage(role=ChatRole.USER, content=f"Transaction digest:\n{facts}"),
            ),
            max_tokens=MAX_ANSWER_TOKENS,
        )
        try:
            return self._gateway.structured(
                request, Triage, case_id=f"monitor_{d.transaction_id}"
            ).value
        except LlmError:
            return None
