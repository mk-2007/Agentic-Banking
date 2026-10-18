"""Labelled, randomised traffic: people behaving honestly or not, with a label we wrote first.

Hand-written scenarios prove the system follows the policy on cases built around its
thresholds. This module makes the opposite test: a *persona* (an honest shopper, an account
taker, a card tester...)
produces a different sequence of payments for every seed, scaled to the account's own habits, and
the label comes from the persona's intent, not from what our thresholds say. The table of labels
below was written before the first run and is not changed to fit a result.

The generator is pure: it returns events. Posting them to a bank and reading what the platform did
is the runner's job (`nexa.api.sim`). Honest limits: personas are our idea of fraud, the amounts and
timings are drawn from ranges we chose, and an episode is a handful of payments, not a life.
"""

import random
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from nexa.domain.actions import ActionType
from nexa.domain.indicators import IndicatorCode

A = ActionType
# From least to most consequential; an episode is judged by the most severe action any case got.
SEVERITY: Final = (
    A.NO_ACTION,
    A.MONITOR_ACCOUNT,
    A.REQUEST_KYC_DOCUMENTS,
    A.ESCALATE_TO_ANALYST,
    A.REQUEST_CUSTOMER_VERIFICATION,
    A.BLOCK_CARD,
    A.FREEZE_ACCOUNT,
)


class Kind(StrEnum):
    """Whether the persona is a genuine customer or an attacker."""

    HONEST = "honest"
    FRAUD = "fraud"


@dataclass(frozen=True)
class Label:
    """What a good outcome is for a persona."""

    kind: Kind
    acceptable: frozenset[ActionType]  # fraud: the most severe action must be one of these
    overreach: frozenset[
        ActionType
    ]  # an action that would wrongly restrict or contact the customer
    preferred: ActionType | None  # the best answer, where there is one
    story: str
    signature: IndicatorCode | None = None  # the finding that names what this persona does


# Written before the first run. Honest personas must not be restricted; fraud personas must be
# caught (a case opened and a human involved), and over-restriction is wrong for both.
LABELS: Final[dict[str, Label]] = {
    "honest_routine": Label(
        Kind.HONEST,
        frozenset({A.NO_ACTION, A.MONITOR_ACCOUNT}),
        frozenset({A.FREEZE_ACCOUNT, A.BLOCK_CARD, A.REQUEST_CUSTOMER_VERIFICATION}),
        None,
        "Everyday spending within the customer's habits.",
    ),
    "honest_big_purchase": Label(
        Kind.HONEST,
        frozenset({A.NO_ACTION, A.MONITOR_ACCOUNT, A.ESCALATE_TO_ANALYST}),
        frozenset({A.FREEZE_ACCOUNT, A.BLOCK_CARD}),
        None,
        "One large but ordinary purchase (a phone, a trip), from their own device.",
    ),
    "honest_new_payee": Label(
        Kind.HONEST,
        frozenset({A.NO_ACTION, A.MONITOR_ACCOUNT, A.ESCALATE_TO_ANALYST}),
        frozenset({A.FREEZE_ACCOUNT, A.BLOCK_CARD}),
        None,
        "A normal transfer to someone they have not paid before, from their own device.",
    ),
    "takeover": Label(
        Kind.FRAUD,
        frozenset({A.FREEZE_ACCOUNT, A.ESCALATE_TO_ANALYST, A.REQUEST_CUSTOMER_VERIFICATION}),
        frozenset(),
        A.FREEZE_ACCOUNT,
        "A new device, repeated failed logins, then six quick transfers to new payees.",
        IndicatorCode.RAPID_SERIES,
    ),
    "card_testing": Label(
        Kind.FRAUD,
        frozenset({A.BLOCK_CARD, A.ESCALATE_TO_ANALYST}),
        frozenset({A.FREEZE_ACCOUNT}),
        A.BLOCK_CARD,
        "Four tiny online charges to one merchant from an unknown device, then a large one.",
        IndicatorCode.CARD_TESTING,
    ),
    "structuring": Label(
        Kind.FRAUD,
        frozenset({A.ESCALATE_TO_ANALYST, A.MONITOR_ACCOUNT}),
        frozenset({A.FREEZE_ACCOUNT, A.BLOCK_CARD}),
        A.ESCALATE_TO_ANALYST,
        "Five cash deposits just under the PKR 300,000 line over a few hours.",
        IndicatorCode.POSSIBLE_STRUCTURING,
    ),
    "new_phone": Label(
        Kind.FRAUD,
        frozenset({A.ESCALATE_TO_ANALYST, A.REQUEST_CUSTOMER_VERIFICATION, A.MONITOR_ACCOUNT}),
        frozenset({A.FREEZE_ACCOUNT, A.BLOCK_CARD}),
        A.ESCALATE_TO_ANALYST,
        "A new phone, failed logins and a new payee on a modest payment: not a takeover.",
        IndicatorCode.UNKNOWN_DEVICE,
    ),
}
PERSONAS: Final = tuple(LABELS)


@dataclass(frozen=True)
class Profile:
    """The account's own habits, which the personas scale from."""

    avg_debit: int
    home_country: str
    home_city: str
    balance: int


@dataclass(frozen=True)
class SimEvent:
    """One transaction in an episode."""

    minutes_after_previous: int
    kind: Literal["payment", "deposit"]
    amount: int
    category: str
    channel: str
    country: str
    city: str
    merchant: str
    payee: str | None = None
    device: Literal["registered", "new"] = "registered"
    failed_logins: int = 0


def _round(amount: float, to: int = 50) -> int:
    return max(to, int(amount // to) * to)


def generate(persona: str, seed: int, profile: Profile) -> tuple[SimEvent, ...]:
    """Return the payments ``persona`` makes for ``seed``, scaled to ``profile``'s habits."""
    rng = random.Random(f"{persona}:{seed}")
    avg, home, town = profile.avg_debit, profile.home_country, profile.home_city
    cap = int(profile.balance * 0.8)  # never ask for more than the account holds

    def shop(n: int, category: str, channel: str, factor: tuple[float, float]) -> list[SimEvent]:
        return [
            SimEvent(
                rng.randint(40, 600) if i else 0, "payment",
                min(cap // max(1, n), _round(avg * rng.uniform(*factor))),
                category if category else rng.choice(("grocery", "dining", "fuel", "pharmacy")),
                channel, home, town, f"Shop {rng.randint(100, 999)}",
            )
            for i in range(n)
        ]  # fmt: skip

    if persona == "honest_routine":
        return tuple(shop(rng.randint(3, 5), "", "pos", (0.2, 1.3)))
    if persona == "honest_big_purchase":
        return tuple(shop(1, rng.choice(("electronics", "retail")), "pos", (2.2, 4.2)))
    if persona == "honest_new_payee":
        amount = min(cap, _round(avg * rng.uniform(0.4, 1.6)))
        return (
            SimEvent(
                0, "payment", amount, "transfer", "mobile_app", home, town,
                f"Friend {rng.randint(10, 99)}", payee=f"PK-{rng.randint(1000, 9999)}",
            ),
        )  # fmt: skip
    if persona == "takeover":
        country = rng.choice((home, "AE"))
        each = min(cap // 6, _round(avg * rng.uniform(0.5, 0.9)))
        fails = rng.randint(3, 6)
        return tuple(
            SimEvent(
                rng.randint(2, 5) if i else 0, "payment", each, "transfer", "mobile_app", country,
                "Dubai" if country == "AE" else town, f"Payee {i}",
                payee=f"PK-{rng.randint(1000, 9999)}",
                device="new", failed_logins=fails,
            )
            for i in range(6)
        )  # fmt: skip
    if persona == "card_testing":
        big = min(cap, rng.randint(25_000, 45_000))
        merchant = f"Web Store {rng.randint(10, 99)}"
        country, city = rng.choice((("US", "Austin"), ("GB", "London"), ("AE", "Dubai")))
        tiny = [
            SimEvent(
                rng.randint(1, 3) if i else 0, "payment", rng.randint(40, 120), "retail",
                "card_online", country, city, merchant, device="new",
            )
            for i in range(4)
        ]  # fmt: skip
        last = SimEvent(
            rng.randint(1, 3), "payment", big, "retail", "card_online", country, city, merchant,
            device="new",
        )  # fmt: skip
        return (*tiny, last)
    if persona == "structuring":
        return tuple(
            SimEvent(
                rng.randint(30, 90) if i else 0, "deposit", rng.randint(190, 285) * 1000, "cash",
                "atm", home, town, "Cash deposit",
            )
            for i in range(5)
        )  # fmt: skip
    if persona == "new_phone":
        amount = min(cap, _round(avg * rng.uniform(0.5, 1.2)))
        return (
            SimEvent(
                0, "payment", amount, "transfer", "mobile_app", home, town,
                f"Payee {rng.randint(10, 99)}", payee=f"PK-{rng.randint(1000, 9999)}",
                device="new", failed_logins=rng.randint(3, 4),
            ),
        )  # fmt: skip
    raise ValueError(f"unknown persona {persona!r}")


@dataclass(frozen=True)
class EpisodeScore:
    """How the platform handled one episode against its label."""

    persona: str
    seed: int
    kind: Kind
    opened: bool
    actions: tuple[str, ...]  # the final recommendation of each case the episode opened
    worst: str | None  # the most severe of them
    safe: bool
    useful: bool
    preferred: bool
    recognised: bool  # a case held the persona's defining finding (False where there is none)


def judge_episode(
    persona: str, seed: int, actions: list[ActionType], codes: frozenset[str] = frozenset()
) -> EpisodeScore:
    """Score the final recommendations of the cases an episode opened (``[]`` = none opened).

    ``codes`` are the finding codes across those cases. ``useful`` asks whether the outcome was
    acceptable; ``recognised`` asks whether the platform saw *why* (a case can escalate by
    accident).
    """
    label = LABELS[persona]
    worst = max(actions, key=SEVERITY.index) if actions else None
    safe = not any(a in label.overreach for a in actions)
    if label.kind is Kind.HONEST:
        useful = safe
        preferred = not actions  # the best outcome for an honest customer is no case at all
    else:
        useful = safe and worst is not None and worst in label.acceptable
        preferred = useful and worst is label.preferred
    return EpisodeScore(
        persona=persona, seed=seed, kind=label.kind, opened=bool(actions),
        actions=tuple(a.value for a in actions), worst=worst.value if worst else None,
        safe=safe, useful=useful, preferred=preferred,
        recognised=label.signature is not None and label.signature.value in codes,
    )  # fmt: skip


@dataclass(frozen=True)
class PersonaTally:
    """Results for one persona."""

    persona: str
    kind: str
    episodes: int
    safe: int
    useful: int
    preferred: int
    opened: int
    recognised: int


@dataclass(frozen=True)
class SimSummary:
    """The headline numbers over a set of episodes."""

    episodes: int
    fraud_episodes: int
    fraud_caught: int  # fraud episodes that were useful: a case opened and handled acceptably
    fraud_recognised: int  # fraud episodes where a case held the persona's defining finding
    honest_episodes: int
    honest_opened: int  # genuine customers who had a case opened on them (a cost, not a harm)
    honest_restricted: int  # genuine customers wrongly restricted or contacted: the harm
    over_restricted: int
    by_persona: tuple[PersonaTally, ...]


def summarise(scores: list[EpisodeScore]) -> SimSummary:
    """Summarise ``scores`` overall and per persona (personas keep their table order)."""
    groups: dict[str, list[EpisodeScore]] = defaultdict(list)
    for s in scores:
        groups[s.persona].append(s)
    fraud = [s for s in scores if s.kind is Kind.FRAUD]
    honest = [s for s in scores if s.kind is Kind.HONEST]
    return SimSummary(
        episodes=len(scores),
        fraud_episodes=len(fraud),
        fraud_caught=sum(s.useful for s in fraud),
        fraud_recognised=sum(s.recognised for s in fraud),
        honest_episodes=len(honest),
        honest_opened=sum(s.opened for s in honest),
        honest_restricted=sum(not s.safe for s in honest),
        over_restricted=sum(not s.safe for s in scores),
        by_persona=tuple(
            PersonaTally(
                p,
                LABELS[p].kind.value,
                len(rows),
                sum(r.safe for r in rows),
                sum(r.useful for r in rows),
                sum(r.preferred for r in rows),
                sum(r.opened for r in rows),
                sum(r.recognised for r in rows),
            )
            for p in PERSONAS
            if (rows := groups.get(p))
        ),  # fmt: skip
    )
