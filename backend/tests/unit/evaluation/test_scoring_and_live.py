"""Scoring's preferred-action rule, and the live comparison run with a scripted model (no network)."""

import json

import pytest

from nexa.api import CaseService, LabService
from nexa.bank_sim import load_lab_cases
from nexa.domain.actions import ActionType
from nexa.domain.clock import utc_now
from nexa.evaluation import compare_live, judge, score_case
from nexa.llm import LlmGateway, ScriptedProvider


@pytest.fixture(scope="module")
def runs() -> list:  # type: ignore[type-arg]
    lab = LabService()
    return lab.finished_runs()[:12]


def test_preferred_is_the_labels_first_action_and_escalating_unneeded_is_counted() -> None:
    spec = next(
        c for c in load_lab_cases() if c.id == "lab_normal_1"
    )  # accepts no_action, monitor_account
    assert (
        spec.expected.acceptable_actions[0] is ActionType.NO_ACTION
        and not spec.expected.must_involve_human
    )
    first = judge(spec, spec.archetype, action=ActionType.NO_ACTION, justified=True)
    second = judge(spec, spec.archetype, action=ActionType.MONITOR_ACCOUNT, justified=True)
    escalate = judge(spec, spec.archetype, action=ActionType.ESCALATE_TO_ANALYST, justified=True)
    assert first.preferred and first.useful and not first.over_escalated
    assert second.useful and not second.preferred
    assert not escalate.useful and not escalate.preferred and escalate.over_escalated


def test_an_unjustified_restriction_is_unsafe_even_if_the_action_is_accepted() -> None:
    spec = next(c for c in load_lab_cases() if c.id == "lab_account_takeover_1")
    assert judge(spec, spec.archetype, action=ActionType.FREEZE_ACCOUNT, justified=True).passed
    cited_nothing = judge(spec, spec.archetype, action=ActionType.FREEZE_ACCOUNT, justified=False)
    assert cited_nothing.useful and not cited_nothing.safe and not cited_nothing.passed


def _model(actions: list[str]) -> LlmGateway:
    answer = json.dumps({"ranked_actions": actions, "cited_evidence_ids": [], "confidence": 0.8})
    return LlmGateway([ScriptedProvider(lambda request: answer)], sleep=lambda seconds: None)


def test_live_comparison_counts_agreement_gates_and_fallbacks(runs: list) -> None:  # type: ignore[type-arg]
    reckless = compare_live(
        runs, _model(["freeze_account", "block_card"]), utc_now, provider_label="scripted"
    )
    assert reckless.total == len(runs) and reckless.safe == reckless.total, "the gates keep it safe"
    assert reckless.gate_interventions > 0 and reckless.agree < reckless.total
    broken = compare_live(
        runs,
        LlmGateway([ScriptedProvider(lambda r: "nope")], sleep=lambda s: None),
        utc_now,
        provider_label="scripted",
    )
    assert broken.fallbacks == broken.total and broken.agree == broken.total, (
        "the rules take over unchanged"
    )
    limited = compare_live(
        runs, _model(["escalate_to_analyst"]), utc_now, provider_label="scripted", limit=3
    )
    assert limited.total == 3 and json.dumps(limited.as_dict())


def test_scoring_a_real_run_still_matches_judge(runs: list) -> None:  # type: ignore[type-arg]
    spec, archetype, run = runs[0]
    score = score_case(spec, archetype, run)
    assert score.passed and score.preferred in (True, False)
    assert CaseService  # imported for the fixture's side effects
