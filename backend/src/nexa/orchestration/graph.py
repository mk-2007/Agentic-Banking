r"""The case graph (Phase 6a): intake, four agents, then ready or failed.

    open_case -> gather -> analyze -> research -> verify -> mark_ready        (DECISION_READY)
                    |         |          |           \-> fail_validation     (FAILED_VALIDATION)
                    \---------+----------+--> a tool problem ends the run     (FAILED_TOOL)

With a decision source (6b) the graph goes on: propose -> request_approval -> await_votes (pauses)
-> settle, which ends in approved, rejected, escalated, timed out or back to decision-ready.

Phase 6c bounds every loop (`RunLimits`: transient tool failures are retried, a case that keeps
waiting on votes is escalated) and, given an audit recorder, writes an audit event for every
transition. The decisions themselves arrive in Phase 7.
"""

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from nexa.agents import Investigation
from nexa.agents.base import AgentContext
from nexa.approvals import InMemoryApprovalStore
from nexa.audit import AuditRecorder
from nexa.domain.approval import ApprovalRequest, ApprovalStatus, ApprovalVote
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import Decision

from .limits import RunLimits
from .nodes import AgentSet, CaseNodes, DecisionSource
from .state import CaseGraphState

CaseGraph: TypeAlias = CompiledStateGraph[CaseGraphState, Any, CaseGraphState, CaseGraphState]


def _continue_or_end(next_node: str) -> Any:
    """Return a router that goes to ``next_node`` unless the run has already failed."""

    def route(state: CaseGraphState) -> str:
        return END if state.get("failure") else next_node

    return route


def _after_verify(state: CaseGraphState) -> Literal["mark_ready", "fail_validation"]:
    return "mark_ready" if state["verification"].passed else "fail_validation"


def _after_propose(state: CaseGraphState) -> str:
    if state.get("failure") or not state["decision"].approval_required:
        return END
    return "request_approval"


def _after_request(state: CaseGraphState) -> str:
    return END if state.get("failure") else "await_votes"


def build_case_graph(
    ctx: AgentContext,
    *,
    agents: AgentSet | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    decide: DecisionSource | None = None,
    audit: AuditRecorder | None = None,
    limits: RunLimits | None = None,
    approvals: InMemoryApprovalStore | None = None,
) -> CaseGraph:
    """Compile the case graph for ``ctx``. Pass ``agents`` to swap a specialist (tests do).

    With ``decide`` the graph continues past ``DECISION_READY``: a recommendation that needs humans
    pauses the run at ``WAITING_FOR_APPROVAL``. Pausing needs a ``checkpointer`` to save the run.
    With ``audit`` every transition, decision, approval request and vote is written to the audit
    chain; ``limits`` bounds retries and vote rounds (defaults are in `RunLimits`).
    With ``approvals`` (the same store the tool registry's `ToolContext` uses) an approved case goes
    on to execute the action through the guarded tool and verify it.
    """
    if approvals is not None and decide is None:
        raise ValueError("executing approved actions needs a decision source")
    if decide is not None and checkpointer is None:
        raise ValueError("a graph that can pause for approval needs a checkpointer")
    nodes = CaseNodes(
        agents or AgentSet.from_context(ctx),
        ctx.clock,
        decide,
        audit=audit,
        limits=limits,
        approvals=approvals,
        registry=ctx.registry,
    )

    def after_settle(state: CaseGraphState) -> str:
        if state["approval"] is ApprovalStatus.PENDING:
            return END if state.get("failure") else "await_votes"
        approved = state["approval"] is ApprovalStatus.APPROVED
        return "execute" if approved and approvals is not None else END

    graph = StateGraph(CaseGraphState)
    for name, step in (
        ("open_case", nodes.open_case),
        ("gather", nodes.gather),
        ("analyze", nodes.analyze),
        ("research", nodes.research),
        ("verify", nodes.verify),
        ("mark_ready", nodes.mark_ready),
        ("fail_validation", nodes.fail_validation),
    ):
        graph.add_node(name, step)
    graph.add_edge(START, "open_case")
    graph.add_edge("open_case", "gather")
    graph.add_conditional_edges("gather", _continue_or_end("analyze"))
    graph.add_conditional_edges("analyze", _continue_or_end("research"))
    graph.add_conditional_edges("research", _continue_or_end("verify"))
    graph.add_conditional_edges("verify", _after_verify)
    if decide is None:
        graph.add_edge("mark_ready", END)
    else:
        for name, step in (
            ("propose", nodes.propose),
            ("request_approval", nodes.request_approval),
            ("await_votes", nodes.await_votes),
            ("settle", nodes.settle),
            *((("execute", nodes.execute),) if approvals is not None else ()),
        ):
            graph.add_node(name, step)
        graph.add_edge("mark_ready", "propose")
        graph.add_conditional_edges("propose", _after_propose)
        graph.add_conditional_edges("request_approval", _after_request)
        graph.add_edge("await_votes", "settle")
        graph.add_conditional_edges("settle", after_settle)
    graph.add_edge("fail_validation", END)
    return graph.compile(checkpointer=checkpointer)


@dataclass(frozen=True)
class CaseRun:
    """The outcome of running (or resuming) a case through the graph."""

    case: Case
    trail: tuple[CaseStatus, ...]
    failure: str | None
    investigation: Investigation | None
    decision: Decision | None = None
    approval_request: ApprovalRequest | None = None
    votes: tuple[ApprovalVote, ...] = ()
    approval: ApprovalStatus | None = None

    @property
    def ready_for_decision(self) -> bool:
        """True when the case reached ``DECISION_READY``."""
        return self.case.status is CaseStatus.DECISION_READY

    @property
    def awaiting_approval(self) -> bool:
        """True when the run is paused for human votes."""
        return self.case.status is CaseStatus.WAITING_FOR_APPROVAL


def _to_run(final: dict[str, Any]) -> CaseRun:
    investigation = (
        Investigation(
            dossier=final["dossier"],
            findings=tuple(final["findings"]),
            policy=final["policy"],
            verification=final["verification"],
        )
        if {"dossier", "findings", "policy", "verification"} <= final.keys()
        else None
    )
    return CaseRun(
        final["case"],
        tuple(final["trail"]),
        final.get("failure"),
        investigation,
        decision=final.get("decision"),
        approval_request=final.get("approval_request"),
        votes=tuple(final.get("votes", ())),
        approval=final.get("approval"),
    )


def run_case(
    case: Case,
    ctx: AgentContext,
    *,
    agents: AgentSet | None = None,
    graph: CaseGraph | None = None,
    thread_id: str | None = None,
) -> CaseRun:
    """Run a new case through the graph and return what happened.

    ``graph`` lets a caller reuse one compiled graph (for example one with a checkpointer, in which
    case ``thread_id`` names the saved run). A run that needs human approval returns paused, with
    ``awaiting_approval`` true; continue it with `resume_case`.
    """
    if case.status is not CaseStatus.CREATED:
        raise ValueError(f"run_case starts new cases; this one is already {case.status.value}")
    compiled = graph or build_case_graph(ctx, agents=agents)
    config: Any = {"configurable": {"thread_id": thread_id or case.id}}
    return _to_run(compiled.invoke({"case": case, "trail": [case.status]}, config))


def resume_case(graph: CaseGraph, thread_id: str, votes: list[ApprovalVote]) -> CaseRun:
    """Give a paused case the votes received so far and continue it.

    Votes are judged by the pure approval rule, not here. If they do not settle the request (for
    example a second approver is still missing) the case stays paused and can be resumed again.
    """
    config: Any = {"configurable": {"thread_id": thread_id}}
    saved = graph.get_state(config).values
    if not saved or saved["case"].status is not CaseStatus.WAITING_FOR_APPROVAL:
        raise ValueError(f"run {thread_id} is not waiting for approval")
    return _to_run(graph.invoke(Command(resume=votes), config))
