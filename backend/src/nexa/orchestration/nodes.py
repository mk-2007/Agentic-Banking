"""The graph's steps. Each one runs a single agent and moves the case to the right status.

The case status changes only here, and only through `Case.transition_to`, which rejects any move
the state machine does not allow. The agents never see the status, and nothing a model says can
change it.

Failures are states, not crashes: when a tool refuses or returns inconsistent records, the case
moves to ``FAILED_TOOL`` and the run ends cleanly with a code recording why.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from langgraph.types import interrupt

from nexa.agents import (
    AgentDataError,
    AgentToolError,
    AnalysisAgent,
    DataAgent,
    Investigation,
    PolicyAgent,
    VerificationAgent,
)
from nexa.agents.base import AgentContext
from nexa.agents.verification_agent import BLOCKING
from nexa.config.approval_matrix import approval_rule_for
from nexa.domain.approval import ApprovalRequest, ApprovalStatus, ApprovalVote, evaluate_approval
from nexa.domain.case import Case, CaseStatus
from nexa.domain.clock import Clock
from nexa.domain.decision import BLOCKING_UNCERTAINTY, Decision
from nexa.domain.evidence import Evidence
from nexa.domain.ids import new_id

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


class DecisionSource(Protocol):
    """Turns a verified investigation into a recommendation (Phase 7 supplies real ones)."""

    def __call__(self, case: Case, investigation: Investigation) -> Decision:
        """Return a ranked recommendation for ``case``."""
        ...


class CaseNodes:
    """The step functions, bound to a set of agents, a clock and (optionally) a decision source."""

    def __init__(
        self, agents: AgentSet, clock: Clock, decide: DecisionSource | None = None
    ) -> None:
        self._agents = agents
        self._clock = clock
        self._decide = decide

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

    # --- decision and human approval (6b) --------------------------------------------------
    def propose(self, state: CaseGraphState) -> Update:
        """Ask the decision source for a recommendation and check it fits this case.

        A recommendation that is for another case, or that ignores blocking uncertainty found by
        verification, is refused: the case ends ``BLOCKED_BY_POLICY`` with a code.
        """
        assert self._decide is not None  # the graph only has this step when a source is given
        case, report = state["case"], state["verification"]
        investigation = Investigation(
            dossier=state["dossier"],
            findings=tuple(state["findings"]),
            policy=state["policy"],
            verification=report,
        )
        decision = self._decide(case, investigation)
        ignored = (BLOCKING_UNCERTAINTY & set(report.uncertainty_flags)) - set(
            decision.uncertainty_flags
        )
        problem = (
            "decision:wrong_case"
            if decision.case_id != case.id
            else "decision:ignored_uncertainty"
            if ignored
            else None
        )
        if problem:
            case, moved = self._move(case, CaseStatus.BLOCKED_BY_POLICY)
            return {"case": case, "trail": moved, "failure": problem}
        case = case.model_copy(update={"decision_id": decision.id})
        return {"case": case, "decision": decision}

    def request_approval(self, state: CaseGraphState) -> Update:
        """Build the approval request from the approval matrix and move to waiting_for_approval."""
        case, decision = state["case"], state["decision"]
        rule = approval_rule_for(decision.recommended_action)
        if rule is None:  # a Level 3+ action with no matrix entry: refuse rather than guess
            case, moved = self._move(case, CaseStatus.BLOCKED_BY_POLICY)
            return {"case": case, "trail": moved, "failure": "approval:no_rule"}
        now = self._clock()
        request = ApprovalRequest(
            id=new_id("apr"),
            case_id=case.id,
            decision_id=decision.id,
            target_account_id=case.alert.account_id,
            action=decision.recommended_action,
            risk_level=decision.risk_level,
            required_roles=rule.required_roles,
            requested_at=now,
            expires_at=now + timedelta(minutes=rule.expiry_minutes),
        )
        case, moved = self._move(case, CaseStatus.WAITING_FOR_APPROVAL)
        return {"case": case, "trail": moved, "approval_request": request}

    def await_votes(self, state: CaseGraphState) -> Update:
        """Pause the run until humans vote. The graph is saved here and resumed with the votes."""
        request = state["approval_request"]
        received = interrupt(
            {
                "approval_id": request.id,
                "action": request.action.value,
                "required_roles": [r.value for r in request.required_roles],
                "expires_at": request.expires_at.isoformat(),
            }
        )
        return {"votes": [ApprovalVote.model_validate(v) for v in received]}

    def settle(self, state: CaseGraphState) -> Update:
        """Apply the pure approval rule to the votes; still pending means wait for more."""
        request = state["approval_request"]
        status = evaluate_approval(request, state.get("votes", []), self._clock())
        target = {
            ApprovalStatus.APPROVED: CaseStatus.APPROVED,
            ApprovalStatus.REJECTED: CaseStatus.REJECTED_BY_HUMAN,
            ApprovalStatus.ESCALATED: CaseStatus.ESCALATED,
            ApprovalStatus.EXPIRED: CaseStatus.TIMED_OUT,
            ApprovalStatus.MODIFICATION_REQUESTED: CaseStatus.DECISION_READY,
        }.get(status)
        if target is None:  # still pending
            return {"approval": status}
        case, moved = self._move(state["case"], target)
        return {"case": case, "trail": moved, "approval": status}
