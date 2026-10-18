"""Every action in the closed set is carried out by a guarded tool, and only as policy allows.

Level 1-2 actions run on their own (nothing a customer holds is restricted). Level 3 and 4 actions run
only with a valid, single-use approval. This is the path that was untested before: an approved
`request_customer_verification` case used to end `failed_tool`.
"""

import dataclasses
from datetime import timedelta

import pytest
from agent_world import NOW, World
from langgraph.checkpoint.memory import MemorySaver

from nexa.agents import Investigation
from nexa.agents.base import AgentContext
from nexa.approvals import InMemoryApprovalStore
from nexa.audit import AuditRecorder
from nexa.bank_sim.models import AccountStatus, CardStatus, OutboxKind
from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalVote, Verdict
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
from nexa.orchestration.nodes import EXECUTOR, PERFORM_TOOL
from nexa.tools import build_default_registry

S = CaseStatus
A = ActionType
D_CASE = "scenario_d_conflicting_evidence"
B_CASE = "scenario_b_suspicious"
F_CASE = "scenario_f_account_takeover"


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


def vote(request_id: str, who: str, role: Role) -> ApprovalVote:
    return ApprovalVote(
        request_id=request_id,
        approver_id=who,
        role=role,
        verdict=Verdict.APPROVE,
        decided_at=NOW + timedelta(minutes=5),
    )


class Harness:
    def __init__(self, world: World, scenario: str, action: ActionType) -> None:
        self.store = InMemoryApprovalStore()
        self.world = world
        world.tools = dataclasses.replace(world.tools, approvals=self.store)
        self.ctx: AgentContext = dataclasses.replace(world.context(), clock=lambda: NOW)
        self.graph: CaseGraph = build_case_graph(
            self.ctx,
            checkpointer=MemorySaver(serde=checkpoint_serde()),
            decide=lambda case, inv: decision_for(case, inv, action),
            approvals=self.store,
            audit=AuditRecorder(world.log, clock=lambda: NOW),
        )
        self.case = world.case(scenario)
        self.account_id = self.case.alert.account_id

    def start(self) -> CaseRun:
        return run_case(self.case, self.ctx, graph=self.graph, thread_id="t")

    def resume(self, *votes: ApprovalVote) -> CaseRun:
        return resume_case(self.graph, "t", list(votes))

    def followups(self) -> tuple[OutboxKind, ...]:
        return tuple(e.kind for e in self.world.tools.bank.followups(self.account_id))

    def executed(self) -> list[str]:
        return [
            e.detail
            for e in self.world.log.for_case(self.case.id)
            if e.event_type is AuditEventType.ACTION_EXECUTED
        ]


# --- Level 3 and 4: an approved action completes, and only through its own tool --------------
def test_an_approved_customer_verification_request_completes_instead_of_failing(
    world: World,
) -> None:
    h = Harness(world, D_CASE, A.REQUEST_CUSTOMER_VERIFICATION)
    paused = h.start()
    assert paused.awaiting_approval and h.followups() == ()  # nothing is sent before approval
    rid = paused.approval_request.id  # type: ignore[union-attr]
    done = h.resume(vote(rid, "ana", Role.FRAUD_ANALYST))
    assert done.case.status is S.COMPLETED and done.failure is None
    assert done.trail[-4:] == (S.APPROVED, S.EXECUTED, S.VERIFIED, S.COMPLETED)
    assert h.followups() == (OutboxKind.VERIFICATION_REQUEST,)
    account = world.tools.bank.get_account(h.account_id)
    assert account.status is AccountStatus.ACTIVE and account.card_status is CardStatus.ACTIVE
    assert len(h.executed()) == 1 and rid in h.executed()[0]


def test_the_other_level_three_and_four_paths_still_complete(world: World) -> None:
    block = Harness(world, B_CASE, A.BLOCK_CARD)
    rid = block.start().approval_request.id  # type: ignore[union-attr]
    assert block.resume(vote(rid, "ana", Role.FRAUD_ANALYST)).case.status is S.COMPLETED
    assert block.followups() == ()  # a card block is not a follow-up

    freeze = Harness(world, F_CASE, A.FREEZE_ACCOUNT)
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    run = freeze.resume(vote(rid, "ana", Role.FRAUD_ANALYST), vote(rid, "rob", Role.RISK_OFFICER))
    assert run.case.status is S.COMPLETED


def test_a_verification_request_without_an_approval_is_refused_by_the_tool(world: World) -> None:
    h = Harness(world, D_CASE, A.REQUEST_CUSTOMER_VERIFICATION)
    h.start()
    result = build_default_registry(world.tools).invoke(
        ToolCall(
            id="x",
            tool_name=PERFORM_TOOL,
            actor=EXECUTOR,
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": "request_customer_verification"},
            requested_at=NOW,
        )
    )
    assert not result.ok and result.error_code == "approval_required"
    assert h.followups() == ()


def test_an_approval_for_one_action_cannot_authorize_another(world: World) -> None:
    h = Harness(world, F_CASE, A.FREEZE_ACCOUNT)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    h.resume(vote(rid, "ana", Role.FRAUD_ANALYST), vote(rid, "rob", Role.RISK_OFFICER))
    result = build_default_registry(world.tools).invoke(
        ToolCall(
            id="x",
            tool_name=PERFORM_TOOL,
            actor=EXECUTOR,
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": "request_customer_verification"},
            approval_id=rid,
            requested_at=NOW,
        )
    )
    assert not result.ok and result.error_code == "approval_mismatch"


def test_a_used_verification_approval_cannot_be_replayed(world: World) -> None:
    h = Harness(world, D_CASE, A.REQUEST_CUSTOMER_VERIFICATION)
    rid = h.start().approval_request.id  # type: ignore[union-attr]
    assert h.resume(vote(rid, "ana", Role.FRAUD_ANALYST)).case.status is S.COMPLETED
    replay = build_default_registry(world.tools).invoke(
        ToolCall(
            id="replay",
            tool_name=PERFORM_TOOL,
            actor=EXECUTOR,
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": "request_customer_verification"},
            approval_id=rid,
            requested_at=NOW,
        )
    )
    assert not replay.ok and replay.error_code == "approval_already_used"
    assert h.followups() == (OutboxKind.VERIFICATION_REQUEST,)  # still just the one


# --- the tool is the executor's alone, and cannot restrict an account -----------------------
@pytest.mark.parametrize("role", [Role.DATA_AGENT, Role.ANALYSIS_AGENT, Role.POLICY_AGENT])
def test_an_agent_cannot_perform_a_case_action(world: World, role: Role) -> None:
    h = Harness(world, D_CASE, A.ESCALATE_TO_ANALYST)
    result = build_default_registry(world.tools).invoke(
        ToolCall(
            id="x",
            tool_name=PERFORM_TOOL,
            actor=Actor(kind=ActorKind.AGENT, id=f"{role.value}_1", role=role),
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": "escalate_to_analyst"},
            requested_at=NOW,
        )
    )
    assert not result.ok and result.error_code == "role_not_permitted"
    assert h.followups() == ()


@pytest.mark.parametrize("action", ["freeze_account", "block_card"])
def test_the_case_action_tool_cannot_restrict_an_account(world: World, action: str) -> None:
    h = Harness(world, F_CASE, A.FREEZE_ACCOUNT)
    result = build_default_registry(world.tools).invoke(
        ToolCall(
            id="x",
            tool_name=PERFORM_TOOL,
            actor=EXECUTOR,
            case_id=h.case.id,
            arguments={"account_id": h.account_id, "action": action},
            requested_at=NOW,
        )
    )
    assert not result.ok and result.error_code == "unsupported_action"
    account = world.tools.bank.get_account(h.account_id)
    assert account.status is AccountStatus.ACTIVE and account.card_status is CardStatus.ACTIVE


# --- Level 1 and 2: the system acts on its own, and says why no approval was asked ----------
@pytest.mark.parametrize(
    ("scenario", "action", "followup"),
    [
        ("scenario_a_normal", A.NO_ACTION, None),
        ("scenario_x_prompt_injection", A.MONITOR_ACCOUNT, OutboxKind.WATCH),
        ("scenario_c_incomplete_kyc", A.REQUEST_KYC_DOCUMENTS, OutboxKind.KYC_REQUEST),
        ("scenario_h_thin_history", A.ESCALATE_TO_ANALYST, OutboxKind.ANALYST_TICKET),
    ],
)
def test_a_low_risk_action_runs_on_its_own_and_is_recorded(
    world: World, scenario: str, action: ActionType, followup: OutboxKind | None
) -> None:
    h = Harness(world, scenario, action)
    run = h.start()
    assert run.case.status is S.COMPLETED and run.failure is None and not run.awaiting_approval
    assert run.trail[-5:] == (S.DECISION_READY, S.APPROVED, S.EXECUTED, S.VERIFIED, S.COMPLETED)
    assert h.followups() == (() if followup is None else (followup,))
    assert run.votes == () and run.approval_request is None  # no human was asked
    events = world.log.for_case(h.case.id)
    assert any(
        e.detail == f"policy:no_approval_needed_level_{int(run.decision.risk_level)}"
        for e in events
    )  # type: ignore[union-attr]
    assert len(h.executed()) == 1 and "no approval needed" in h.executed()[0]
    assert world.log.verify() is None
