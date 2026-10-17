"""Naive baselines: what simple rules would do on the same cases, scored the same way.

The point is a fair comparison, not a straw man. Baselines range from "do nothing" to a typical
multi-signal risk score. None of them cites findings or policy, which is part of the difference:
a restriction that cites nothing fails the "justified" check, as it would in a real review.

Baselines read the bank directly (they are not agents), through the same `BankGateway` interface.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nexa.bank_sim import BankGateway
from nexa.bank_sim.scenarios import ScenarioSpec
from nexa.domain.actions import ActionType

from .scoring import CaseScore, Scorecard, judge, scorecard


@dataclass(frozen=True)
class AlertFacts:
    """What a simple rule can see about the alerted payment."""

    amount: int
    average: float
    foreign: bool
    untrusted_device: bool
    new_beneficiary: bool
    failed_logins: int
    history: int

    @property
    def ratio(self) -> float:
        """The payment as a multiple of the customer's average earlier payment."""
        return self.amount / self.average if self.average else float("inf")


def facts_for(bank: BankGateway, spec: ScenarioSpec) -> AlertFacts:
    """Read the alerted transaction and the customer's earlier payments."""
    alert = bank.get_transaction(spec.alert.transaction_id)
    home = bank.get_customer(spec.alert.customer_id).home_country
    earlier = [
        t
        for t in bank.list_transactions(alert.account_id, until=alert.occurred_at)
        if t.id != alert.id and t.direction.value == "debit"
    ]
    return AlertFacts(
        amount=alert.amount,
        average=sum(t.amount for t in earlier) / len(earlier) if earlier else 0.0,
        foreign=alert.country != home,
        untrusted_device=not alert.device_trusted,
        new_beneficiary=alert.is_new_beneficiary,
        failed_logins=alert.failed_auth_attempts_prior_hour,
        history=len(earlier),
    )


def _risk_score(f: AlertFacts) -> int:
    return (
        2 * (f.ratio >= 5)
        + f.foreign
        + f.untrusted_device
        + f.new_beneficiary
        + (f.failed_logins >= 3)
    )


def _score_rule(f: AlertFacts) -> ActionType:
    points = _risk_score(f)
    if points >= 5:
        return ActionType.FREEZE_ACCOUNT
    if points >= 3:
        return ActionType.BLOCK_CARD
    return ActionType.ESCALATE_TO_ANALYST if points >= 1 else ActionType.NO_ACTION


@dataclass(frozen=True)
class Baseline:
    """A simple decision rule."""

    key: str
    title: str
    description: str
    decide: Callable[[AlertFacts], ActionType]


BASELINES: tuple[Baseline, ...] = (
    Baseline("never_act", "Never act", "Approve everything.", lambda f: ActionType.NO_ACTION),
    Baseline(
        "always_escalate",
        "Always escalate",
        "Send every alert to an analyst.",
        lambda f: ActionType.ESCALATE_TO_ANALYST,
    ),
    Baseline(
        "big_amount",
        "Big-amount rule",
        "Block the card at PKR 100,000 or more, otherwise do nothing.",
        lambda f: ActionType.BLOCK_CARD if f.amount >= 100_000 else ActionType.NO_ACTION,
    ),
    Baseline(
        "unusual_amount",
        "Unusual-amount rule",
        "Escalate at five times the customer's average, otherwise do nothing.",
        lambda f: ActionType.ESCALATE_TO_ANALYST if f.ratio >= 5 else ActionType.NO_ACTION,
    ),
    Baseline(
        "risk_score",
        "Multi-signal risk score",
        "Points for amount, country, device, new payee and failed logins; "
        "5+ freeze, 3+ block the card, 1+ escalate.",
        _score_rule,
    ),
)


@dataclass(frozen=True)
class BaselineResult:
    """One baseline's scorecard over the lab cases."""

    key: str
    title: str
    description: str
    card: Scorecard


def run_baselines(
    bank: BankGateway, cases: Sequence[tuple[ScenarioSpec, str]]
) -> list[BaselineResult]:
    """Score every baseline on every case with the same checks the agents face."""
    facts = [(spec, arch, facts_for(bank, spec)) for spec, arch in cases]
    results: list[BaselineResult] = []
    for baseline in BASELINES:
        scores: list[CaseScore] = [
            judge(spec, arch, action=baseline.decide(f), justified=False) for spec, arch, f in facts
        ]
        results.append(
            BaselineResult(baseline.key, baseline.title, baseline.description, scorecard(scores))
        )
    return results
