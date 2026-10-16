r"""The case graph (Phase 6a): intake, four agents, then ready or failed.

    open_case -> gather -> analyze -> research -> verify -> mark_ready        (DECISION_READY)
                    |         |          |           \-> fail_validation     (FAILED_VALIDATION)
                    \---------+----------+--> a tool problem ends the run     (FAILED_TOOL)

Not built yet, by design: the human approval pause (6b); loop limits, retries and audit events for
every transition (6c); and the decision itself, which arrives in Phase 7 behind ``DECISION_READY``.
"""

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from nexa.agents import Investigation
from nexa.agents.base import AgentContext
from nexa.domain.case import Case, CaseStatus

from .nodes import AgentSet, CaseNodes
from .state import CaseGraphState

CaseGraph: TypeAlias = CompiledStateGraph[CaseGraphState, Any, CaseGraphState, CaseGraphState]


def _continue_or_end(next_node: str) -> Any:
    """Return a router that goes to ``next_node`` unless the run has already failed."""

    def route(state: CaseGraphState) -> str:
        return END if state.get("failure") else next_node

    return route


def _after_verify(state: CaseGraphState) -> Literal["mark_ready", "fail_validation"]:
    return "mark_ready" if state["verification"].passed else "fail_validation"


def build_case_graph(
    ctx: AgentContext,
    *,
    agents: AgentSet | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CaseGraph:
    """Compile the case graph for ``ctx``. Pass ``agents`` to swap a specialist (tests do)."""
    nodes = CaseNodes(agents or AgentSet.from_context(ctx), ctx.clock)
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
    graph.add_edge("mark_ready", END)
    graph.add_edge("fail_validation", END)
    return graph.compile(checkpointer=checkpointer)


@dataclass(frozen=True)
class CaseRun:
    """The outcome of running a case through the graph."""

    case: Case
    trail: tuple[CaseStatus, ...]
    failure: str | None
    investigation: Investigation | None

    @property
    def ready_for_decision(self) -> bool:
        """True when the case reached ``DECISION_READY``."""
        return self.case.status is CaseStatus.DECISION_READY


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
    case ``thread_id`` names the saved run).
    """
    if case.status is not CaseStatus.CREATED:
        raise ValueError(f"run_case starts new cases; this one is already {case.status.value}")
    compiled = graph or build_case_graph(ctx, agents=agents)
    config: Any = {"configurable": {"thread_id": thread_id or case.id}}
    final = compiled.invoke({"case": case, "trail": [case.status]}, config)

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
    return CaseRun(final["case"], tuple(final["trail"]), final.get("failure"), investigation)
