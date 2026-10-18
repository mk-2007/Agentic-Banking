"""The case pauses for humans, resumes with their votes, and ends in the status the rule gives."""

import dataclasses
import logging
from datetime import datetime, timedelta

import pytest
from agent_world import NOW, World
from langgraph.checkpoint.memory import MemorySaver

from nexa.agents import Investigation
from nexa.agents.base import AgentContext
from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Role
from nexa.domain.approval import ApprovalStatus, ApprovalVote, Verdict
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import CandidateScore, Decision, UncertaintyFlag
from nexa.orchestration import (
    CaseGraph,
    CaseRun,
    build_case_graph,
    checkpoint_serde,
    resume_case,
    run_case,
)

S = CaseStatus
FREEZE_CASE = "scenario_f_account_takeover"


def decision_for(
    case: Case,
    inv: Investigation,
    action: ActionType,
    *,
    case_id: str | None = None,
    flags: tuple[UncertaintyFlag, ...] = (),
) -> Decision:
    level = risk_level_for(action)
    support = tuple(f.id for f in inv.findings[:2]) if level.requires_human_approval else ()
    return Decision(
        id=f"dec_{case.id}",
        case_id=case_id or case.id,
        ranked_candidates=(
            CandidateScore(action=action, score=0.9, supporting_evidence_ids=support),
        ),
        recommended_action=action,
        risk_level=level,
        approval_required=level.requires_human_approval,
        uncertainty_flags=flags,
        evidence_strength=0.8,
        policy_refs=inv.policy.policy_refs[:1] if level.requires_human_approval else (),
        provider="test",
        created_at=NOW,
    )


def vote(request_id: str, who: str, role: Role, verdict: Verdict, minutes: int = 5) -> ApprovalVote:
    return ApprovalVote(
        request_id=request_id,
        approver_id=who,
        role=role,
        verdict=verdict,
        decided_at=NOW + timedelta(minutes=minutes),
    )


class Harness:
    def __init__(self, world: World, scenario: str, action: ActionType, **kw: object) -> None:
        self.now = NOW
        self.ctx: AgentContext = dataclasses.replace(world.context(), clock=lambda: self.now)
        self.saver = MemorySaver(serde=checkpoint_serde())
        self.graph: CaseGraph = build_case_graph(
            self.ctx,
            checkpointer=self.saver,
            decide=lambda case, inv: decision_for(case, inv, action, **kw),  # type: ignore[arg-type]
        )
        self.case = world.case(scenario)

    def start(self) -> CaseRun:
        return run_case(self.case, self.ctx, graph=self.graph, thread_id="t")

    def resume(self, *votes: ApprovalVote) -> CaseRun:
        return resume_case(self.graph, "t", list(votes))


@pytest.fixture
def freeze(world: World) -> Harness:
    return Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT)


def test_a_level_four_recommendation_pauses_for_two_named_roles(freeze: Harness) -> None:
    run = freeze.start()
    request = run.approval_request
    assert run.awaiting_approval and run.trail[-1] is S.WAITING_FOR_APPROVAL
    assert request is not None and run.decision is not None
    assert set(request.required_roles) == {Role.FRAUD_ANALYST, Role.RISK_OFFICER}
    assert request.target_account_id == freeze.case.alert.account_id
    assert request.case_id == freeze.case.id and request.decision_id == run.decision.id
    assert request.expires_at - request.requested_at == timedelta(minutes=120)
    assert run.case.decision_id == run.decision.id
    assert run.approval is None  # nobody has voted


def test_two_different_roles_must_approve_and_one_is_not_enough(freeze: Harness) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    one = freeze.resume(vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE))
    assert one.awaiting_approval and one.approval is ApprovalStatus.PENDING
    both = freeze.resume(vote(rid, "rob", Role.RISK_OFFICER, Verdict.APPROVE))
    assert both.case.status is S.APPROVED and both.approval is ApprovalStatus.APPROVED
    assert len(both.votes) == 2  # votes accumulate across resumes
    assert both.trail[-3:] == (S.DECISION_READY, S.WAITING_FOR_APPROVAL, S.APPROVED)


def test_the_same_role_twice_does_not_make_two_approvers(freeze: Harness) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    run = freeze.resume(
        vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE),
        vote(rid, "bea", Role.FRAUD_ANALYST, Verdict.APPROVE),
    )
    assert run.awaiting_approval and run.approval is ApprovalStatus.PENDING


def test_votes_for_another_request_are_ignored(freeze: Harness) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    run = freeze.resume(
        vote("apr_other", "ana", Role.FRAUD_ANALYST, Verdict.APPROVE),
        vote("apr_other", "rob", Role.RISK_OFFICER, Verdict.APPROVE),
    )
    assert run.awaiting_approval and rid != "apr_other"


@pytest.mark.parametrize(
    ("verdict", "status", "approval"),
    [
        (Verdict.REJECT, S.REJECTED_BY_HUMAN, ApprovalStatus.REJECTED),
        (Verdict.ESCALATE, S.ESCALATED, ApprovalStatus.ESCALATED),
        (Verdict.MODIFY, S.ESCALATED, ApprovalStatus.MODIFICATION_REQUESTED),
    ],
)
def test_one_negative_vote_ends_the_approval(
    freeze: Harness, verdict: Verdict, status: S, approval: ApprovalStatus
) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    run = freeze.resume(
        vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE),
        vote(rid, "rob", Role.RISK_OFFICER, verdict),
    )
    assert run.case.status is status and run.approval is approval


def test_an_approval_that_runs_out_of_time_times_the_case_out(freeze: Harness) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    freeze.now = NOW + timedelta(minutes=121)
    late = freeze.resume(vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE, minutes=10))
    assert late.case.status is S.TIMED_OUT and late.approval is ApprovalStatus.EXPIRED


def test_votes_cast_after_expiry_cannot_approve(freeze: Harness) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    freeze.now = NOW + timedelta(minutes=121)
    run = freeze.resume(
        vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE, minutes=130),
        vote(rid, "rob", Role.RISK_OFFICER, Verdict.APPROVE, minutes=130),
    )
    assert run.case.status is S.TIMED_OUT


def test_a_low_risk_recommendation_does_not_pause(world: World) -> None:
    run = Harness(world, "scenario_a_normal", ActionType.NO_ACTION).start()
    assert run.case.status is S.DECISION_READY and run.approval_request is None
    assert run.decision is not None and not run.awaiting_approval


def test_a_decision_for_another_case_is_blocked(world: World) -> None:
    run = Harness(world, FREEZE_CASE, ActionType.FREEZE_ACCOUNT, case_id="case_other").start()
    assert run.case.status is S.BLOCKED_BY_POLICY and run.failure == "decision:wrong_case"
    assert run.approval_request is None


def test_a_decision_that_ignores_verification_uncertainty_is_blocked(world: World) -> None:
    run = Harness(world, "scenario_d_conflicting_evidence", ActionType.ESCALATE_TO_ANALYST).start()
    assert UncertaintyFlag.CONFLICTING_EVIDENCE in run.investigation.verification.uncertainty_flags  # type: ignore[union-attr]
    assert run.case.status is S.BLOCKED_BY_POLICY and run.failure == "decision:ignored_uncertainty"


def test_a_decision_that_keeps_the_uncertainty_flags_goes_ahead(world: World) -> None:
    flags = (UncertaintyFlag.CONFLICTING_EVIDENCE,)
    run = Harness(
        world, "scenario_d_conflicting_evidence", ActionType.ESCALATE_TO_ANALYST, flags=flags
    ).start()
    assert run.case.status is S.DECISION_READY and run.failure is None


def test_pausing_needs_a_checkpointer_and_only_paused_runs_resume(
    world: World, freeze: Harness
) -> None:
    ctx = world.context()
    with pytest.raises(ValueError, match="checkpointer"):
        build_case_graph(ctx, decide=lambda c, i: decision_for(c, i, ActionType.NO_ACTION))
    low = Harness(world, "scenario_a_normal", ActionType.NO_ACTION)
    low.start()
    with pytest.raises(ValueError, match="not waiting"):
        low.resume()
    with pytest.raises(ValueError, match="not waiting"):
        resume_case(freeze.graph, "never-started", [])


def test_a_paused_case_resumes_from_a_fresh_graph_with_nothing_refused(
    freeze: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    rid = freeze.start().approval_request.id  # type: ignore[union-attr]
    again = build_case_graph(  # a new process would rebuild the graph and reuse the saved state
        freeze.ctx,
        checkpointer=freeze.saver,
        decide=lambda c, i: decision_for(c, i, ActionType.FREEZE_ACCOUNT),
    )
    with caplog.at_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus"):
        run = resume_case(
            again,
            "t",
            [
                vote(rid, "ana", Role.FRAUD_ANALYST, Verdict.APPROVE),
                vote(rid, "rob", Role.RISK_OFFICER, Verdict.APPROVE),
            ],
        )
    assert not [r for r in caplog.records if "Blocked" in r.getMessage()]
    assert run.case.status is S.APPROVED
    assert isinstance(run.votes[0].decided_at, datetime)
    assert run.decision is not None and run.decision.recommended_action is ActionType.FREEZE_ACCOUNT
