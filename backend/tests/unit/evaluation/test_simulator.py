"""The labelled traffic generator: deterministic per seed, shaped like its story, honestly judged."""

import pytest

from nexa.domain.actions import ActionType
from nexa.domain.indicators import IndicatorCode
from nexa.evaluation import LABELS, PERSONAS, Profile, generate, judge_episode, summarise
from nexa.evaluation.simulator import SEVERITY, Kind

A = ActionType
PROFILE = Profile(avg_debit=16_000, home_country="PK", home_city="Karachi", balance=270_000)
SEEDS = range(1, 41)


def test_the_same_seed_gives_the_same_episode_and_other_seeds_differ() -> None:
    for persona in PERSONAS:
        assert generate(persona, 7, PROFILE) == generate(persona, 7, PROFILE)
    assert len({generate("honest_routine", s, PROFILE) for s in SEEDS}) > 30


@pytest.mark.parametrize("persona", PERSONAS)
def test_no_episode_asks_for_more_than_the_account_holds(persona: str) -> None:
    for seed in SEEDS:
        events = generate(persona, seed, PROFILE)
        spent = sum(e.amount for e in events if e.kind == "payment")
        assert events and spent <= PROFILE.balance and all(e.amount > 0 for e in events)


def test_each_persona_looks_like_its_story() -> None:
    for seed in SEEDS:
        take = generate("takeover", seed, PROFILE)
        assert len(take) == 6 and all(e.device == "new" and e.failed_logins >= 3 for e in take)
        assert (
            len({e.payee for e in take}) == 6 and sum(e.minutes_after_previous for e in take) <= 25
        )

        test = generate("card_testing", seed, PROFILE)
        *tiny, big = test
        assert len(tiny) == 4 and len({e.merchant for e in test}) == 1
        assert all(e.amount <= 0.02 * big.amount for e in tiny)  # "very small" by policy
        assert {e.country for e in test} != {"PK"}

        dep = generate("structuring", seed, PROFILE)
        assert len(dep) == 5 and all(e.kind == "deposit" for e in dep)
        assert all(0.6 * 300_000 <= e.amount < 300_000 for e in dep)  # just under the line

        phone = generate("new_phone", seed, PROFILE)
        assert len(phone) == 1 and phone[0].device == "new" and 3 <= phone[0].failed_logins <= 4

        for persona in ("honest_routine", "honest_big_purchase", "honest_new_payee"):
            for e in generate(persona, seed, PROFILE):
                assert e.device == "registered" and e.failed_logins == 0 and e.country == "PK"
        big = generate("honest_big_purchase", seed, PROFILE)[0]
        assert big.amount < 5 * PROFILE.avg_debit  # large, but not past the policy's 5x line


def test_the_labels_are_consistent() -> None:
    assert set(LABELS) == set(PERSONAS) and len(PERSONAS) == 7
    for persona, label in LABELS.items():
        assert not (label.acceptable & label.overreach), persona
        if label.kind is Kind.FRAUD:
            assert label.acceptable and label.preferred in label.acceptable, persona
            assert label.signature is not None, persona
            assert A.NO_ACTION not in label.acceptable  # a fraud persona is never fine to ignore
        else:
            assert label.signature is None and A.FREEZE_ACCOUNT in label.overreach, persona


def test_severity_orders_every_action() -> None:
    assert set(SEVERITY) == set(A) and SEVERITY[-1] is A.FREEZE_ACCOUNT


def test_an_honest_customer_is_best_served_by_no_case_and_must_never_be_restricted() -> None:
    quiet = judge_episode("honest_routine", 1, [])
    assert quiet.safe and quiet.useful and quiet.preferred and not quiet.opened
    watched = judge_episode("honest_big_purchase", 1, [A.NO_ACTION])
    assert watched.safe and watched.useful and not watched.preferred and watched.opened
    harmed = judge_episode("honest_new_payee", 1, [A.ESCALATE_TO_ANALYST, A.FREEZE_ACCOUNT])
    assert not harmed.safe and not harmed.useful and harmed.worst == "freeze_account"


def test_a_fraud_persona_must_be_caught_and_handled_acceptably() -> None:
    assert not judge_episode("takeover", 1, []).useful  # nothing opened: missed
    assert not judge_episode("takeover", 1, [A.MONITOR_ACCOUNT]).useful  # opened, but waved through
    ok = judge_episode("takeover", 1, [A.ESCALATE_TO_ANALYST, A.FREEZE_ACCOUNT])
    assert ok.useful and ok.preferred and ok.worst == "freeze_account"
    only_escalated = judge_episode("takeover", 1, [A.ESCALATE_TO_ANALYST])
    assert only_escalated.useful and not only_escalated.preferred
    over = judge_episode("card_testing", 1, [A.FREEZE_ACCOUNT])
    assert not over.safe and not over.useful  # freezing a card-testing victim is over-reach


def test_recognised_asks_whether_the_platform_saw_why_not_just_what_it_did() -> None:
    code = IndicatorCode.POSSIBLE_STRUCTURING.value
    accident = judge_episode(
        "structuring", 1, [A.ESCALATE_TO_ANALYST], frozenset({"familiar_merchant"})
    )
    seen = judge_episode("structuring", 1, [A.ESCALATE_TO_ANALYST], frozenset({code}))
    assert accident.useful and not accident.recognised  # right answer, wrong reason
    assert seen.useful and seen.recognised
    assert not judge_episode("honest_routine", 1, [], frozenset({code})).recognised


def test_the_summary_counts_what_matters() -> None:
    scores = [
        judge_episode("honest_routine", 1, []),
        judge_episode("honest_new_payee", 1, [A.ESCALATE_TO_ANALYST]),
        judge_episode("honest_big_purchase", 1, [A.FREEZE_ACCOUNT]),
        judge_episode("takeover", 1, [A.FREEZE_ACCOUNT], frozenset({"rapid_series"})),
        judge_episode("structuring", 1, []),
    ]
    s = summarise(scores)
    assert (s.episodes, s.fraud_episodes, s.honest_episodes) == (5, 2, 3)
    assert (s.fraud_caught, s.fraud_recognised) == (1, 1)
    assert (s.honest_opened, s.honest_restricted, s.over_restricted) == (2, 1, 1)
    assert [p.persona for p in s.by_persona] == [
        "honest_routine", "honest_big_purchase", "honest_new_payee", "takeover", "structuring",
    ]  # fmt: skip


def test_an_unknown_persona_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown persona"):
        generate("pickpocket", 1, PROFILE)
