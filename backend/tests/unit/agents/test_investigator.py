"""The model-driven investigator and its fact-checker.

The model proposes; code decides. These tests script the model (no network) and check that a claim
only becomes a finding when what the model actually looked at supports it, that the model can add a
finding the baseline never searches for but cannot invent or remove one, that every lookup stays
inside the tool layer's rules, and that no third-party text reaches a prompt.
"""

import dataclasses
import json

import pytest
from agent_world import NOW, World

from nexa.agents import (
    AgenticAnalysis,
    AnalysisAgent,
    DataAgent,
    InquiryOutcome,
    PolicyAgent,
    VerificationAgent,
    code_of,
)
from nexa.agents.base import AgentContext, agent_actor
from nexa.agents.verification_agent import IssueCode
from nexa.domain.actors import Role
from nexa.domain.audit import AuditEventType
from nexa.domain.evidence import Evidence
from nexa.domain.indicators import IndicatorCode
from nexa.domain.tooling import ToolCall
from nexa.llm import LlmGateway, LlmRequest, ScriptedProvider

C = IndicatorCode
ACCOUNTS = {
    "scenario_a_normal": "acc_101",
    "scenario_b_suspicious": "acc_102",
    "scenario_f_account_takeover": "acc_106",
    "scenario_x_prompt_injection": "acc_107",
    "scenario_i_structuring": "acc_110",
    "scenario_j_new_phone": "acc_111",
}


def say(**fields: object) -> str:
    return json.dumps(fields)


def history_call(account: str) -> str:
    return say(
        action="call",
        lookup="get_transaction_history",
        arguments={"account_id": account, "since": "2026-07-01", "limit": 500},
    )


def conclude(*claims: tuple[str, tuple[str, ...]]) -> str:
    return say(action="conclude", claims=[{"code": c, "cited": list(o)} for c, o in claims])


class Setup:
    """An investigator wired to the real bank and tool layer, with a scripted model."""

    def __init__(self, world: World, scenario: str, script: object) -> None:
        self.world = world
        self.provider = ScriptedProvider(script)  # type: ignore[arg-type]
        gateway = LlmGateway([self.provider], sleep=lambda s: None)
        self.ctx: AgentContext = dataclasses.replace(
            world.context(gateway=gateway), investigate=True
        )
        self.case = world.case(scenario)
        self.account = ACCOUNTS[scenario]
        self.dossier = DataAgent(self.ctx).gather(self.case)

    def run(self):  # type: ignore[no-untyped-def]
        return AgenticAnalysis(self.ctx).analyze(self.case, self.dossier)

    def policy(self) -> PolicyAgent:
        # retrieval only: the scripted model has no answer for the policy agent's narrowing step
        return PolicyAgent(dataclasses.replace(self.ctx, gateway=None))

    def baseline(self) -> tuple[Evidence, ...]:
        return AnalysisAgent(self.ctx).analyze(self.case, self.dossier)


def codes(findings: tuple[Evidence, ...]) -> set[IndicatorCode]:
    return {c for e in findings if (c := code_of(e)) is not None}


# --- a claim becomes a finding only when what the model saw supports it ---------------------------
def test_claims_the_baseline_also_finds_are_confirmed_and_change_nothing(world: World) -> None:
    obs = ("obs_1",)
    s = Setup(
        world,
        "scenario_f_account_takeover",
        [
            history_call("acc_106"),
            conclude(
                ("rapid_series", obs),
                ("new_beneficiary", obs),
                ("unknown_device", obs),
                ("failed_auth", obs),
            ),  # fmt: skip
        ],
    )
    out = s.run()
    r = out.report
    assert r.outcome is InquiryOutcome.CONCLUDED and r.dropped == () and r.added == ()
    assert set(r.confirmed) == {"rapid_series", "new_beneficiary", "unknown_device", "failed_auth"}
    assert codes(out.findings) == codes(s.baseline())  # the model added nothing, removed nothing
    assert set(r.missed).isdisjoint(r.claimed)
    assert [t.tool for t in r.trace] == ["get_transaction_history"] and r.trace[0].ok


def test_an_overreaching_claim_is_dropped_and_never_becomes_a_finding(world: World) -> None:
    # Scenario J is a PKR 18,000 payment. A real model once claimed it was high-value.
    obs = ("obs_1",)
    s = Setup(
        world,
        "scenario_j_new_phone",
        [history_call("acc_111"), conclude(("high_value", obs), ("amount_above_average", obs))],
    )
    out = s.run()
    assert {d.code for d in out.report.dropped} == {"high_value", "amount_above_average"}
    assert {d.reason for d in out.report.dropped} == {"unsupported"}
    assert C.HIGH_VALUE not in codes(out.findings)
    assert codes(out.findings) == codes(s.baseline())


def test_a_claim_needs_citations_that_exist(world: World) -> None:
    s = Setup(
        world,
        "scenario_f_account_takeover",
        [
            history_call("acc_106"),
            say(
                action="conclude",
                claims=[
                    {"code": "rapid_series", "cited": []},
                    {"code": "failed_auth", "cited": ["obs_9"]},
                    {"code": "unknown_device", "cited": ["obs_1"]},
                ],
            ),
        ],
    )
    reasons = {d.code: d.reason for d in s.run().report.dropped}
    assert reasons == {"rapid_series": "uncited", "failed_auth": "unknown_observation"}


def test_the_model_cannot_confirm_what_it_never_looked_at(world: World) -> None:
    # It concludes at once, citing only the alert, so it has no history to support a baseline claim.
    s = Setup(world, "scenario_b_suspicious", [conclude(("amount_above_average", ("alert",)))])
    out = s.run()
    assert [d.reason for d in out.report.dropped] == ["unsupported"]
    assert C.AMOUNT_ABOVE_AVERAGE in codes(out.findings)  # the baseline still found it itself
    assert "amount_above_average" in out.report.claimed


def test_each_code_is_claimed_once_however_often_the_model_repeats_it(world: World) -> None:
    obs = ("obs_1",)
    s = Setup(
        world,
        "scenario_f_account_takeover",
        [history_call("acc_106"), conclude(("failed_auth", obs), ("failed_auth", obs))],
    )
    assert s.run().report.claimed == ("failed_auth",)


# --- what only the model looks for: structuring ---------------------------------------------------
def test_the_model_can_add_structuring_when_the_policy_criteria_hold(world: World) -> None:
    s = Setup(
        world,
        "scenario_i_structuring",
        [history_call("acc_110"), conclude(("possible_structuring", ("obs_1",)))],
    )
    assert C.POSSIBLE_STRUCTURING not in codes(s.baseline())  # the arithmetic never looks for it
    out = s.run()
    assert out.report.added == ("possible_structuring",) and out.report.dropped == ()
    found = next(e for e in out.findings if code_of(e) is C.POSSIBLE_STRUCTURING)
    assert found.data["origin"] == "model" and int(found.data["qualifying_payments"]) >= 4  # type: ignore[arg-type]
    # the verification agent recomputes it from the numbers it recorded
    report = VerificationAgent(s.ctx.thresholds).verify(
        s.case, s.dossier, out.findings, s.policy().research(s.case, out.findings)
    )
    assert report.passed and not report.issues


def test_a_forged_structuring_finding_is_caught_by_verification(world: World) -> None:
    s = Setup(
        world,
        "scenario_i_structuring",
        [history_call("acc_110"), conclude(("possible_structuring", ("obs_1",)))],
    )
    out = s.run()
    forged = tuple(
        e.model_copy(update={"data": {**e.data, "qualifying_payments": 2}})
        if code_of(e) is C.POSSIBLE_STRUCTURING
        else e
        for e in out.findings
    )
    report = VerificationAgent(s.ctx.thresholds).verify(
        s.case, s.dossier, forged, s.policy().research(s.case, forged)
    )
    assert not report.passed
    assert IssueCode.UNSUPPORTED_FINDING in {i.code for i in report.issues}


@pytest.mark.parametrize("scenario", ["scenario_a_normal", "scenario_b_suspicious"])
def test_structuring_is_not_added_where_the_pattern_is_absent(world: World, scenario: str) -> None:
    s = Setup(
        world,
        scenario,
        [history_call(ACCOUNTS[scenario]), conclude(("possible_structuring", ("obs_1",)))],
    )
    out = s.run()
    assert out.report.added == () and [d.reason for d in out.report.dropped] == ["unsupported"]
    assert C.POSSIBLE_STRUCTURING not in codes(out.findings)


# --- the tool layer still rules every lookup ------------------------------------------------------
def test_a_lookup_outside_the_case_is_refused_and_audited(world: World) -> None:
    other = say(action="call", lookup="get_account_details", arguments={"account_id": "acc_102"})
    s = Setup(world, "scenario_a_normal", [other, conclude()])
    out = s.run()
    assert out.report.outcome is InquiryOutcome.CONCLUDED
    assert [(t.ok, t.error_code) for t in out.report.trace] == [(False, "out_of_scope")]
    denied = [
        e
        for e in world.log.for_case(s.case.id)
        if e.event_type is AuditEventType.TOOL_DENIED and "investigator_agent" in e.actor.id
    ]
    assert len(denied) == 1


@pytest.mark.parametrize(
    "tool", ["execute_authorized_action", "perform_case_action", "search_knowledge_base"]
)
def test_the_investigator_cannot_act_or_read_policy(world: World, tool: str) -> None:
    s = Setup(world, "scenario_a_normal", [conclude()])
    result = s.ctx.registry.invoke(
        ToolCall(
            id="x",
            tool_name=tool,
            actor=agent_actor(Role.INVESTIGATOR_AGENT),
            case_id=s.case.id,
            arguments={"account_id": s.account, "action": "freeze_account", "query": "x"},
            requested_at=NOW,
        )
    )
    assert not result.ok and result.error_code == "role_not_permitted"


# --- a missing, broken or endless model costs nothing ----------------------------------------------
def test_a_model_that_returns_garbage_leaves_exactly_the_baseline(world: World) -> None:
    s = Setup(world, "scenario_f_account_takeover", ["not json", "still not json", "nope"])
    out = s.run()
    assert out.report.outcome is InquiryOutcome.MODEL_UNAVAILABLE and out.report.claimed == ()
    assert codes(out.findings) == codes(s.baseline())
    assert out.report.missed == ()  # a run that never concluded is not scored against the model


def test_a_model_that_never_concludes_runs_out_of_steps(world: World) -> None:
    ask = say(action="call", lookup="get_customer_profile", arguments={"customer_id": "cust_101"})
    s = Setup(world, "scenario_a_normal", [ask] * 6)
    out = s.run()
    assert out.report.outcome is InquiryOutcome.OUT_OF_STEPS and len(out.report.trace) == 6
    assert codes(out.findings) == codes(s.baseline())


def test_a_claim_that_depends_on_text_the_model_never_sees_is_refused_and_repaired(
    world: World,
) -> None:
    bad = conclude(("instruction_text", ("alert",)))
    good = conclude(("trusted_device", ("alert",)))
    s = Setup(world, "scenario_a_normal", [bad, good])
    out = s.run()
    assert out.report.repairs == 1 and "instruction_text" not in out.report.claimed


# --- no third-party text reaches a prompt ----------------------------------------------------------
@pytest.mark.parametrize("scenario", list(ACCOUNTS))
def test_no_merchant_name_or_memo_reaches_a_prompt(world: World, scenario: str) -> None:
    seen: list[LlmRequest] = []
    state = {"n": 0}

    def script(request: LlmRequest) -> str:
        seen.append(request)
        state["n"] += 1
        if state["n"] == 1:
            return history_call(ACCOUNTS[scenario])
        return conclude(("trusted_device", ("alert",)))

    s = Setup(world, scenario, script)
    s.run()
    prompts = " ".join(m.content for r in seen for m in r.messages).lower()
    forbidden = {
        text
        for t in world.tools.bank.list_transactions(s.account)
        for text in (t.merchant_name, t.memo)
        if len(text) >= 6
    }
    assert forbidden, "the scenario should have text to leak"
    assert not [text for text in forbidden if text.lower() in prompts]
