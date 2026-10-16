"""The LangGraph graph and case state machine.

Why: Coordinates agents, enforces loop limits and pauses for human approval (PRD sections
    37-39). Phase 6a builds the graph from intake to ``DECISION_READY``; approvals and loop limits
    follow in 6b and 6c.

Where it sits: Layer 4. Composes agents, approvals and decision.

Modules:
    state       what a case carries through the graph (contracts and lists only)
    nodes       the steps, and the only place the case status changes
    graph       `build_case_graph` and `run_case`
    checkpoint  the types a saved case may be rebuilt from
"""

from .checkpoint import ALLOWED_TYPES, checkpoint_serde
from .graph import CaseGraph, CaseRun, build_case_graph, run_case
from .nodes import AgentSet
from .state import CaseGraphState

__all__ = [
    "ALLOWED_TYPES",
    "AgentSet",
    "CaseGraph",
    "CaseGraphState",
    "CaseRun",
    "build_case_graph",
    "checkpoint_serde",
    "run_case",
]
