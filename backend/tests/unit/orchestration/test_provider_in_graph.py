"""The rule-based provider drives the whole graph, from alert to a completed freeze."""

import dataclasses
from datetime import timedelta

import pytest
from agent_world import NOW, SCENARIOS, World
from langgraph.checkpoint.memory import MemorySaver

from nexa.approvals import InMemoryApprovalStore
from nexa.bank_sim.models import AccountStatus
from nexa.decision import RuleBasedDecisionProvider
from nexa.domain.actors import Role
from nexa.domain.approval import ApprovalVote, Verdict
from nexa.domain.case import CaseStatus
from nexa.orchestration import (
    build_case_graph,
    checkpoint_serde,
    provider_source,
    resume_case,
    run_case,
)

S = CaseStatus


def graph_for(world: World, store: InMemoryApprovalStore):  # type: ignore[no-untyped-def]
    world.tools = dataclasses.replace(world.tools, approvals=store)
    ctx = world.context()
    graph = build_case_graph(
        ctx,
        checkpointer=MemorySaver(serde=checkpoint_serde()),
        decide=provider_source(RuleBasedDecisionProvider(lambda: NOW)),
        approvals=store,
    )
    return ctx, graph


def vote(rid: str, who: str, role: Role) -> ApprovalVote:
    return ApprovalVote(
        request_id=rid,
        approver_id=who,
        role=role,
        verdict=Verdict.APPROVE,
        decided_at=NOW + timedelta(minutes=5),
    )


def test_an_account_takeover_goes_from_alert_to_a_frozen_account_through_two_humans(
    world: World,
) -> None:
    ctx, graph = graph_for(world, InMemoryApprovalStore())
    case = world.case("scenario_f_account_takeover")
    paused = run_case(case, ctx, graph=graph, thread_id="t")
    assert paused.awaiting_approval and paused.decision is not None
    assert paused.decision.recommended_action.value == "freeze_account"
    assert paused.decision.provider == "rule_based_v1" and paused.decision.overridden_by is None
    rid = paused.approval_request.id  # type: ignore[union-attr]
    done = resume_case(
        graph,
        "t",
        [vote(rid, "ana", Role.FRAUD_ANALYST), vote(rid, "rob", Role.RISK_OFFICER)],
    )
    assert done.case.status is S.COMPLETED
    assert world.tools.bank.get_account(case.alert.account_id).status is AccountStatus.FROZEN


@pytest.mark.parametrize(
    "scenario_id", [s for s in SCENARIOS if s != "scenario_f_account_takeover"]
)
def test_no_other_scenario_is_blocked_or_changes_the_bank_without_approval(
    world: World, scenario_id: str
) -> None:
    ctx, graph = graph_for(world, InMemoryApprovalStore())
    case = world.case(scenario_id)
    run = run_case(case, ctx, graph=graph, thread_id="t")
    assert run.failure is None and run.case.status in (S.DECISION_READY, S.WAITING_FOR_APPROVAL)
    assert run.decision is not None
    assert world.tools.bank.get_account(case.alert.account_id).status is AccountStatus.ACTIVE
