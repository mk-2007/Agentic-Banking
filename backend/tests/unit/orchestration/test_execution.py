"""An approved action is executed through the guarded tool, and only then; every scenario runs end to end."""

import dataclasses
from datetime import timedelta

import pytest
from agent_world import NOW, SCENARIOS, World
from langgraph.checkpoint.memory import MemorySaver

from nexa.agents import Investigation
from nexa.agents.base import AgentContext
from nexa.approvals import InMemoryApprovalStore
from nexa.bank_sim.models import AccountStatus, CardStatus
from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.domain.audit import AuditEventType
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import CandidateScore, Decision
from nexa.domain.tooling import ToolCall
from nexa.orchestration import (
    CaseGraph,
    CaseRun,
    build_case_graph,
    checkpoint_serde,
    resume_case,
    run_case,
)
from nexa.orchestration.nodes import EXECUTE_TOOL, EXECUTOR
from nexa.tools import build_default_registry

S = CaseStatus
FREEZE_CASE = "scenario_f_account_takeover"
SUSPICIOUS_CASE = "scenario_b_suspicious"


def decision_for(case: Case, inv: Investigation, action: ActionType) -> Decision:
    level = risk_level_for(action)
    support = tuple(f.id for f in inv.findings[:2]) if level.requires_human_approval else ()
    return Decision(
        id=f"dec_{case.id}",
        case_id=case.id,
        ranked_candidates=(
            CandidateScore(action=action, score=0.9, supporting_evidence_ids=support),
        ),
        recommended_action=action,
        risk_level=level,
        approval_required=level.requires_human_approval,
        uncertainty_flags=inv.verification.uncertainty_flags,
        evidence_strength=0.8,
        policy_refs=inv.policy.policy_refs[:1] if level.requires_human_approval else (),
        provider="test",
        created_at=NOW,
    )


def vote(request_id: str, who: str, role: Role, verdict: Verdict = Verdict.APPROVE) -> ApprovalVote:
    return ApprovalVote(
        request_id=request_id,
        approver_id=who,
        role=role,
        verdict=verdict,
        decided_at=NOW + timedelta(minutes=5),
    )


class Harness:
    """One graph wired to a shared approval store, so the tool and the graph see the same approvals."""

    def __init__(self, world: World, scenario: str, action: ActionType) -> None:
        self.now = NOW
        self.store = InMemoryApprovalStore()
        self.world = world
        world.tools = dataclasses.replace(world.tools, approvals=self.store)
        self.ctx: AgentContext = dataclasses.replace(world.context(), clock=lambda: self.now)
        self.graph: CaseGraph = build_case_graph(
            self.ctx,
            checkpointer=MemorySaver(serde=checkpoint_serde()),
            decide=lambda case, inv: decision_for(case, inv, action),
            approvals=self.store,
        )
        self.case = world.case(scenario)
        self.account_id = self.case.alert.account_id

    def start(self) -> CaseRun:
        return run_case(self.case, self.ctx, graph=self.graph, thread_id="t")

    def resume(self, *votes: ApprovalVote) -> CaseRun:
        return resume_case(self.graph, "t", list(votes))

    def account(self):  # type: ignore[no-untyped-def]
        return self.world.tools.bank.get_account(self.account_id)


def both(rid: str) -> tuple[ApprovalVote, ApprovalVote]:
    return (
        vote(rid, "ana", Role.FRAUD_ANALYST),
        vote(rid, "rob", Role.RISK_OFFICER),
    )


# --- the Level 4 path ---------------------------------------------------------------------
def test_two_approvers_freeze_the_account_and_the_case_completes(world: World) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    paused = h.start()
    assert paused.awaiting_approval and h.account().status is AccountStatus.ACTIVE
    rid = paused.approval_request.id  # type: ignore[union-attr]
    done = h.resume(*both(rid))
    assert done.case.status is S.COMPLETED and done.failure is None
    assert done.trail[-5:] == (
        S.WAITING_FOR_APPROVAL,
        S.APPROVED,
        S.EXECUTED,
        S.VERIFIED,
        S.COMPLETED,
    )
    assert h.account().status is AccountStatus.FROZEN
    executed = [
        e for e in world.log.for_case(h.case.id) if e.event_type is AuditEventType.ACTION_EXECUTED
    ]
    assert len(executed) == 1 and rid in executed[0].detail
    assert world.log.verify() is None


def test_one_approver_is_not_enough_and_nothing_is_executed(world: World) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    run = h.resume(vote(rid, "ana", Role.FRAUD_ANALYST))
    assert run.awaiting_approval and h.account().status is AccountStatus.ACTIVE


@pytest.mark.parametrize("verdict", [Verdict.REJECT, Verdict.ESCALATE, Verdict.MODIFY])
def test_a_negative_verdict_never_executes(world: World, verdict: Verdict) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    run = h.resume(
        vote(rid, "ana", Role.FRAUD_ANALYST), vote(rid, "rob", Role.RISK_OFFICER, verdict)
    )
    assert run.case.status is not S.COMPLETED and h.account().status is AccountStatus.ACTIVE


def test_an_expired_approval_never_executes(world: World) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    h.now = NOW + timedelta(minutes=121)
    run = h.resume(*both(rid))
    assert run.case.status is S.TIMED_OUT and h.account().status is AccountStatus.ACTIVE


def test_an_approval_cannot_be_replayed_after_it_was_used(world: World) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    assert h.resume(*both(rid)).case.status is S.COMPLETED
    replay = build_default_registry(world.tools).invoke(
        ToolCall(
            id="replay",
            tool_name=EXECUTE_TOOL,
            actor=EXECUTOR,
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": "freeze_account"},
            approval_id=rid,
            requested_at=NOW,
        )
    )
    assert not replay.ok and replay.error_code == "approval_already_used"


def test_a_refused_execution_ends_the_case_failed_tool_with_a_code(world: World) -> None:
    h = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    h.store.try_consume(rid)  # someone used the approval behind the graph's back
    run = h.resume(*both(rid))
    assert run.case.status is S.FAILED_TOOL
    assert run.failure == f"{EXECUTE_TOOL}:approval_already_used"
    assert h.account().status is AccountStatus.ACTIVE


# --- the Level 3 path ---------------------------------------------------------------------
def test_one_analyst_blocks_the_card_for_a_level_three_action(world: World) -> None:
    h = Harness(world, SUSPICIOUS_CASE, ActionType.BLOCK_CARD)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    run = h.resume(vote(rid, "ana", Role.FRAUD_ANALYST))
    assert run.case.status is S.COMPLETED
    assert h.account().card_status is CardStatus.BLOCKED
    assert h.account().status is AccountStatus.ACTIVE  # block_card does not freeze the account


# --- configuration and the store ----------------------------------------------------------
def test_without_a_store_an_approved_case_stops_at_approved(world: World) -> None:
    ctx = world.context()
    graph = build_case_graph(
        ctx,
        checkpointer=MemorySaver(serde=checkpoint_serde()),
        decide=lambda case, inv: decision_for(case, inv, ActionType.FREEZE_ACCOUNT),
    )
    case = world.case(FREEZE_CASE)
    rid = run_case(case, ctx, graph=graph, thread_id="t").approval_request.id  # type: ignore[union-attr]
    run = resume_case(graph, "t", list(both(rid)))
    assert run.case.status is S.APPROVED
    assert world.tools.bank.get_account(case.alert.account_id).status is AccountStatus.ACTIVE


def test_executing_needs_a_decision_source(world: World) -> None:
    with pytest.raises(ValueError, match="decision source"):
        build_case_graph(world.context(), approvals=InMemoryApprovalStore())


def request(approval_id: str = "apr_1") -> ApprovalRequest:
    return ApprovalRequest(
        id=approval_id,
        case_id="case_1",
        decision_id="dec_1",
        target_account_id="acc_1",
        action=ActionType.FREEZE_ACCOUNT,
        risk_level=risk_level_for(ActionType.FREEZE_ACCOUNT),
        required_roles=(Role.FRAUD_ANALYST, Role.RISK_OFFICER),
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=2),
    )


def test_the_store_consumes_an_approval_exactly_once() -> None:
    store = InMemoryApprovalStore()
    store.add_request(request())
    assert store.try_consume("apr_1") is True
    assert store.try_consume("apr_1") is False
    assert store.try_consume("apr_unknown") is False


def test_the_store_rejects_duplicates_and_votes_for_unknown_requests() -> None:
    store = InMemoryApprovalStore()
    store.add_request(request())
    with pytest.raises(ValueError, match="already exists"):
        store.add_request(request())
    with pytest.raises(KeyError):
        store.set_votes("apr_unknown", [])
    assert store.get_request("apr_unknown") is None and store.get_votes("apr_unknown") == ()


# --- every scenario through the whole graph -----------------------------------------------
@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_every_scenario_runs_end_to_end_without_unapproved_changes(
    world: World, scenario_id: str
) -> None:
    expected = SCENARIOS[scenario_id].expected
    action = expected.acceptable_actions[0] if expected.acceptable_actions else ActionType.NO_ACTION
    h = Harness(world, scenario_id, action)
    run = h.start()
    assert run.failure is None
    assert action not in expected.forbidden_actions
    if expected.must_involve_human and risk_level_for(action).requires_human_approval:
        assert run.awaiting_approval
    else:
        assert run.case.status is S.DECISION_READY and not run.awaiting_approval
    assert h.account().status is AccountStatus.ACTIVE  # nothing changed without an approval
    assert not [
        e for e in world.log.for_case(h.case.id) if e.event_type is AuditEventType.ACTION_EXECUTED
    ]
