"""Loops are bounded, transient failures are retried once, and every transition is audited."""

import dataclasses
from datetime import timedelta

import pytest
from agent_world import NOW, World
from langgraph.checkpoint.memory import MemorySaver

from nexa.agents import AgentToolError, AnalysisAgent
from nexa.agents.dossier import Dossier
from nexa.audit import AuditRecorder, InMemoryAuditLog
from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import ActorKind, Role
from nexa.domain.approval import ApprovalVote, Verdict
from nexa.domain.audit import AuditEventType
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import CandidateScore, Decision
from nexa.domain.evidence import Evidence
from nexa.orchestration import (
    AgentSet,
    RunLimits,
    build_case_graph,
    checkpoint_serde,
    resume_case,
    run_case,
)

S = CaseStatus
FREEZE_CASE = "scenario_f_account_takeover"
CLEAN_CASE = "scenario_a_normal"


class FlakyAnalysis(AnalysisAgent):
    """Fails with ``code`` for the first ``failures`` calls, then behaves normally."""

    def __init__(self, ctx: object, code: str, failures: int) -> None:
        super().__init__(ctx)  # type: ignore[arg-type]
        self.code, self.failures, self.calls = code, failures, 0

    def analyze(self, case: Case, dossier: Dossier) -> tuple[Evidence, ...]:
        self.calls += 1
        if self.calls <= self.failures:
            raise AgentToolError("get_transaction_history", self.code)
        return super().analyze(case, dossier)


def flaky(world: World, code: str, failures: int) -> tuple[AgentSet, FlakyAnalysis]:
    ctx = world.context()
    agent = FlakyAnalysis(ctx, code, failures)
    return dataclasses.replace(AgentSet.from_context(ctx), analysis=agent), agent


# --- retries ------------------------------------------------------------------------------
def test_a_transient_tool_failure_is_retried_and_the_case_carries_on(world: World) -> None:
    agents, agent = flaky(world, "timeout", failures=1)
    run = run_case(world.case(CLEAN_CASE), world.context(), agents=agents)
    assert run.ready_for_decision and run.failure is None and agent.calls == 2
    assert tuple(run.trail[2:5]) == (S.EXECUTING, S.WAITING_FOR_TOOL, S.EXECUTING)


def test_the_retry_budget_runs_out_and_the_case_fails_with_a_code(world: World) -> None:
    agents, agent = flaky(world, "timeout", failures=5)
    run = run_case(world.case(CLEAN_CASE), world.context(), agents=agents)
    assert run.case.status is S.FAILED_TOOL
    assert run.failure == "get_transaction_history:timeout" and agent.calls == 2


def test_attempts_can_be_tuned_but_never_below_one(world: World) -> None:
    agents, agent = flaky(world, "timeout", failures=5)
    graph = build_case_graph(world.context(), agents=agents, limits=RunLimits(max_attempts=3))
    run = run_case(world.case(CLEAN_CASE), world.context(), graph=graph)
    assert run.case.status is S.FAILED_TOOL and agent.calls == 3
    with pytest.raises(ValueError, match="at least 1"):
        RunLimits(max_attempts=0)


@pytest.mark.parametrize("code", ["out_of_scope", "role_not_permitted", "invalid_arguments"])
def test_a_refusal_is_never_retried(world: World, code: str) -> None:
    agents, agent = flaky(world, code, failures=1)
    run = run_case(world.case(CLEAN_CASE), world.context(), agents=agents)
    assert run.case.status is S.FAILED_TOOL and agent.calls == 1
    assert run.failure == f"get_transaction_history:{code}"


# --- vote-round limit ---------------------------------------------------------------------
def freeze_decision(case: Case, investigation: object) -> Decision:
    inv = investigation  # an Investigation; typed loosely to keep the stand-in short
    action = ActionType.FREEZE_ACCOUNT
    return Decision(
        id=f"dec_{case.id}",
        case_id=case.id,
        ranked_candidates=(
            CandidateScore(
                action=action,
                score=0.9,
                supporting_evidence_ids=tuple(f.id for f in inv.findings[:2]),  # type: ignore[attr-defined]
            ),
        ),
        recommended_action=action,
        risk_level=risk_level_for(action),
        approval_required=True,
        evidence_strength=0.8,
        policy_refs=inv.policy.policy_refs[:1],  # type: ignore[attr-defined]
        provider="test",
        created_at=NOW,
    )


def analyst_vote(request_id: str, who: str) -> ApprovalVote:
    return ApprovalVote(
        request_id=request_id,
        approver_id=who,
        role=Role.FRAUD_ANALYST,
        verdict=Verdict.APPROVE,
        decided_at=NOW + timedelta(minutes=5),
    )


def paused_graph(world: World, audit: AuditRecorder | None = None, **limits: int) -> object:
    return build_case_graph(
        world.context(),
        checkpointer=MemorySaver(serde=checkpoint_serde()),
        decide=freeze_decision,
        audit=audit,
        limits=RunLimits(**limits),
    )


def test_a_case_that_stays_pending_too_long_is_escalated(world: World) -> None:
    graph = paused_graph(world, max_vote_rounds=2)
    first = run_case(world.case(FREEZE_CASE), world.context(), graph=graph, thread_id="t")  # type: ignore[arg-type]
    rid = first.approval_request.id  # type: ignore[union-attr]
    again = resume_case(graph, "t", [analyst_vote(rid, "ana")])  # type: ignore[arg-type]
    assert again.awaiting_approval  # round 1 of 2: still waiting for the risk officer
    last = resume_case(graph, "t", [analyst_vote(rid, "bea")])  # type: ignore[arg-type]
    assert last.case.status is S.ESCALATED and last.failure == "approval:too_many_rounds"
    with pytest.raises(ValueError, match="not waiting"):
        resume_case(graph, "t", [])  # type: ignore[arg-type]


# --- audit --------------------------------------------------------------------------------
def events_of(log: InMemoryAuditLog, case: Case, kind: AuditEventType) -> list[str]:
    return [e.detail for e in log.for_case(case.id) if e.event_type is kind]


def test_every_status_change_is_in_the_audit_chain_in_order(world: World) -> None:
    log = InMemoryAuditLog()
    graph = build_case_graph(world.context(), audit=AuditRecorder(log, clock=lambda: NOW))
    case = world.case(CLEAN_CASE)
    run = run_case(case, world.context(), graph=graph)
    changes = events_of(log, case, AuditEventType.STATE_CHANGED)
    assert changes == [
        f"{a.value}->{b.value}" for a, b in zip(run.trail, run.trail[1:], strict=False)
    ]
    assert events_of(log, case, AuditEventType.CASE_CREATED)
    assert log.verify() is None
    assert all(
        e.actor.kind is ActorKind.SYSTEM
        for e in log.for_case(case.id)
        if e.event_type is AuditEventType.STATE_CHANGED
    )


def test_failures_decisions_approvals_and_votes_are_audited(world: World) -> None:
    log = InMemoryAuditLog()
    graph = paused_graph(world, AuditRecorder(log, clock=lambda: NOW))
    case = world.case(FREEZE_CASE)
    paused = run_case(case, world.context(), graph=graph, thread_id="t")  # type: ignore[arg-type]
    rid = paused.approval_request.id  # type: ignore[union-attr]
    resume_case(graph, "t", [analyst_vote(rid, "ana")])  # type: ignore[arg-type]
    assert events_of(log, case, AuditEventType.DECISION_MADE) == ["freeze_account"]
    assert events_of(log, case, AuditEventType.APPROVAL_REQUESTED) == [rid]
    assert events_of(log, case, AuditEventType.APPROVAL_VOTE_CAST) == [
        f"{rid}:fraud_analyst:approve"
    ]
    reviewers = [e.reviewer_id for e in log.for_case(case.id) if e.reviewer_id]
    assert reviewers == ["ana"]
    assert log.verify() is None


def test_a_failed_run_records_its_code_and_a_retry_leaves_a_trace(world: World) -> None:
    log = InMemoryAuditLog()
    agents, _ = flaky(world, "timeout", failures=5)
    graph = build_case_graph(
        world.context(), agents=agents, audit=AuditRecorder(log, clock=lambda: NOW)
    )
    case = world.case(CLEAN_CASE)
    run_case(case, world.context(), graph=graph)
    assert events_of(log, case, AuditEventType.ERROR) == ["get_transaction_history:timeout"]
    changes = events_of(log, case, AuditEventType.STATE_CHANGED)
    assert "executing->waiting_for_tool" in changes and "waiting_for_tool->failed_tool" in changes


def test_without_a_recorder_nothing_is_written_and_nothing_breaks(world: World) -> None:
    run = run_case(world.case(CLEAN_CASE), world.context())
    assert run.ready_for_decision
