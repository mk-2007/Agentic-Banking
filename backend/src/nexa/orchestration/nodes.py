"""The graph's steps. Each one runs a single agent and moves the case to the right status.

The case status changes only here, and only through `Case.transition_to`, which rejects any move
the state machine does not allow. The agents never see the status, and nothing a model says can
change it.

Failures are states, not crashes: when a tool refuses or returns inconsistent records, the case
moves to ``FAILED_TOOL`` and the run ends cleanly with a code recording why.
"""

from collections.abc import Callable
from dataclasses import dataclass

from nexa.agents import (
    AgentDataError,
    AgentToolError,
    AnalysisAgent,
    DataAgent,
    PolicyAgent,
    VerificationAgent,
)
from nexa.agents.base import AgentContext
from nexa.agents.verification_agent import BLOCKING
from nexa.domain.case import Case, CaseStatus
from nexa.domain.clock import Clock
from nexa.domain.evidence import Evidence

from .state import CaseGraphState

Update = dict[str, object]


@dataclass(frozen=True)
class AgentSet:
    """The four specialists. Tests (and later phases) can swap one for a stand-in."""

    data: DataAgent
    analysis: AnalysisAgent
    policy: PolicyAgent
    verification: VerificationAgent

    @classmethod
    def from_context(cls, ctx: AgentContext) -> "AgentSet":
        """Build the standard four from the shared agent settings."""
        return cls(
            data=DataAgent(ctx),
            analysis=AnalysisAgent(ctx),
            policy=PolicyAgent(ctx),
            verification=VerificationAgent(ctx.thresholds),
        )


class CaseNodes:
    """The step functions, bound to a set of agents and a clock."""

    def __init__(self, agents: AgentSet, clock: Clock) -> None:
        self._agents = agents
        self._clock = clock

    # --- helpers ---------------------------------------------------------------------
    def _move(self, case: Case, *statuses: CaseStatus) -> tuple[Case, list[CaseStatus]]:
        for status in statuses:
            case = case.transition_to(status, self._clock())
        return case, list(statuses)

    def _fail_tool(self, case: Case, code: str) -> Update:
        # A tool problem surfaces while the case is executing, so it passes through waiting.
        case, moved = self._move(case, CaseStatus.WAITING_FOR_TOOL, CaseStatus.FAILED_TOOL)
        return {"case": case, "trail": moved, "failure": code}

    def _guarded(
        self, step: Callable[[CaseGraphState], Update]
    ) -> Callable[[CaseGraphState], Update]:
        def run(state: CaseGraphState) -> Update:
            try:
                return step(state)
            except AgentToolError as error:
                return self._fail_tool(state["case"], f"{error.tool_name}:{error.error_code}")
            except AgentDataError:
                return self._fail_tool(state["case"], "records_inconsistent")

        return run

    # --- steps ---------------------------------------------------------------------------
    def open_case(self, state: CaseGraphState) -> Update:
        """Move the case from created to executing. The sequence is fixed; no model plans it."""
        case, moved = self._move(state["case"], CaseStatus.PLANNING, CaseStatus.EXECUTING)
        return {"case": case, "trail": moved}

    def gather(self, state: CaseGraphState) -> Update:
        """Run the data agent to fetch the records."""
        return self._guarded(lambda s: {"dossier": self._agents.data.gather(s["case"])})(state)

    def analyze(self, state: CaseGraphState) -> Update:
        """Run the analysis agent to compute the findings."""

        def step(s: CaseGraphState) -> Update:
            found = self._agents.analysis.analyze(s["case"], s["dossier"])
            return {"findings": list(found)}

        return self._guarded(step)(state)

    def research(self, state: CaseGraphState) -> Update:
        """Run the policy agent to find the clauses that apply."""

        def step(s: CaseGraphState) -> Update:
            return {"policy": self._agents.policy.research(s["case"], s["findings"])}

        return self._guarded(step)(state)

    def verify(self, state: CaseGraphState) -> Update:
        """Run the verification agent, then record every piece of evidence on the case."""
        case, moved = self._move(state["case"], CaseStatus.VERIFYING)
        dossier, findings, policy = state["dossier"], state["findings"], state["policy"]
        report = self._agents.verification.verify(case, dossier, findings, policy)
        evidence: list[Evidence] = [*dossier.evidence, *findings, *policy.evidence]
        case = case.model_copy(update={"evidence_ids": tuple(e.id for e in evidence)})
        return {"case": case, "trail": moved, "verification": report}

    def mark_ready(self, state: CaseGraphState) -> Update:
        """Move a verified case to decision-ready (the decision itself is Phase 7)."""
        case, moved = self._move(state["case"], CaseStatus.DECISION_READY)
        return {"case": case, "trail": moved}

    def fail_validation(self, state: CaseGraphState) -> Update:
        """Stop a case whose verification found a blocking problem, and say which kind."""
        case, moved = self._move(state["case"], CaseStatus.FAILED_VALIDATION)
        issues = sorted({i.code.value for i in state["verification"].issues if i.code in BLOCKING})
        return {"case": case, "trail": moved, "failure": "validation:" + ",".join(issues)}
