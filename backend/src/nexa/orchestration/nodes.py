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
    AgenticAnalysis,
    AgentToolError,
    AnalysisAgent,
    DataAgent,
    InquiryReport,
    Investigation,
    PolicyAgent,
    VerificationAgent,
)
from nexa.agents.base import AgentContext
from nexa.agents.verification_agent import BLOCKING
from nexa.approvals import InMemoryApprovalStore
from nexa.audit import AuditRecorder
from nexa.config.approval_matrix import approval_rule_for
from nexa.domain.actions import ActionType
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalRequest, ApprovalStatus, ApprovalVote, evaluate_approval
from nexa.domain.audit import AuditEventType
from nexa.domain.case import Case, CaseStatus
from nexa.domain.clock import Clock
from nexa.domain.decision import BLOCKING_UNCERTAINTY, Decision
from nexa.domain.evidence import Evidence
from nexa.domain.ids import new_id
from nexa.domain.tooling import ToolCall
from nexa.tools import ToolRegistry
from nexa.tools.execution import EXECUTABLE_ACTIONS

from .limits import TRANSIENT_TOOL_CODES, RunLimits
from .state import CaseGraphState

ORCHESTRATOR = Actor(kind=ActorKind.SYSTEM, id="orchestrator")
EXECUTOR = Actor(kind=ActorKind.SYSTEM, id="executor", role=Role.EXECUTION_SERVICE)
EXECUTE_TOOL = "execute_authorized_action"
PERFORM_TOOL = "perform_case_action"

Update = dict[str, object]


@dataclass(frozen=True)
class AgentSet:
    """The four specialists. Tests (and later phases) can swap one for a stand-in."""

    data: DataAgent
    analysis: AnalysisAgent
    policy: PolicyAgent
    verification: VerificationAgent
    agentic: AgenticAnalysis | None = None  # the model-driven analysis, when it is switched on

    @classmethod
    def from_context(cls, ctx: AgentContext) -> "AgentSet":
        """Build the standard four from the shared agent settings."""
        return cls(
            data=DataAgent(ctx),
            analysis=AnalysisAgent(ctx),
            policy=PolicyAgent(ctx),
            verification=VerificationAgent(ctx.thresholds),
            agentic=AgenticAnalysis(ctx) if ctx.investigate and ctx.gateway else None,
        )


class DecisionSource(Protocol):
    """Turns a verified investigation into a recommendation (Phase 7 supplies real ones)."""

    def __call__(self, case: Case, investigation: Investigation) -> Decision:
        """Return a ranked recommendation for ``case``."""
        ...


class CaseNodes:
    """The step functions, bound to agents, a clock, limits and (optionally) a decision source.

    With an ``audit`` recorder, every status change, decision, approval request, vote and failure
    is written to the audit chain by the orchestrator, so a case can be reconstructed afterwards.
    """

    def __init__(
        self,
        agents: AgentSet,
        clock: Clock,
        decide: DecisionSource | None = None,
        *,
        audit: AuditRecorder | None = None,
        limits: RunLimits | None = None,
        approvals: InMemoryApprovalStore | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self._agents = agents
        self._clock = clock
        self._decide = decide
        self._audit = audit
        self._limits = limits or RunLimits()
        self._approvals = approvals
        self._registry = registry

    # --- helpers ---------------------------------------------------------------------
    def _record(
        self,
        event: AuditEventType,
        case: Case,
        detail: str = "",
        *,
        decision_id: str | None = None,
        approval_status: ApprovalStatus | None = None,
        reviewer_id: str | None = None,
    ) -> None:
        if self._audit is not None:
            self._audit.record(
                event,
                ORCHESTRATOR,
                case_id=case.id,
                detail=detail,
                decision_id=decision_id,
                approval_status=approval_status,
                reviewer_id=reviewer_id,
            )

    def _move(self, case: Case, *statuses: CaseStatus) -> tuple[Case, list[CaseStatus]]:
        for status in statuses:
            before = case.status
            case = case.transition_to(status, self._clock())
            self._record(AuditEventType.STATE_CHANGED, case, f"{before.value}->{status.value}")
        return case, list(statuses)

    def _stop(self, case: Case, status: CaseStatus, code: str) -> Update:
        """End the run in ``status`` with a short failure code, recording both."""
        case, moved = self._move(case, status)
        self._record(AuditEventType.ERROR, case, code)
        return {"case": case, "trail": moved, "failure": code}

    def _fail_tool(self, case: Case, code: str) -> Update:
        # A tool problem surfaces while the case is executing, so it passes through waiting.
        case, moved = self._move(case, CaseStatus.WAITING_FOR_TOOL, CaseStatus.FAILED_TOOL)
        self._record(AuditEventType.ERROR, case, code)
        return {"case": case, "trail": moved, "failure": code}

    def _guarded(
        self, step: Callable[[CaseGraphState], Update]
    ) -> Callable[[CaseGraphState], Update]:
        """Run an agent step with bounded retries; failures become states, never crashes."""

        def run(state: CaseGraphState) -> Update:
            case = state["case"]
            trail: list[CaseStatus] = []
            attempt = 0
            while True:
                attempt += 1
                try:
                    update = step({**state, "case": case})
                except (AgentToolError, AgentDataError) as error:
                    transient = (
                        isinstance(error, AgentToolError)
                        and error.error_code in TRANSIENT_TOOL_CODES
                    )
                    if transient and attempt < self._limits.max_attempts:
                        case, moved = self._move(
                            case, CaseStatus.WAITING_FOR_TOOL, CaseStatus.EXECUTING
                        )
                        trail += moved
                        continue
                    code = (
                        f"{error.tool_name}:{error.error_code}"
                        if isinstance(error, AgentToolError)
                        else "records_inconsistent"
                    )
                    failed = self._fail_tool(case, code)
                    failed["trail"] = [*trail, *failed["trail"]]  # type: ignore[misc]
                    return failed
                if trail:  # retried: carry the moved case and the extra statuses forward
                    return {**update, "case": case, "trail": trail}
                return update

        return run

    # --- steps ---------------------------------------------------------------------------
    def open_case(self, state: CaseGraphState) -> Update:
        """Move the case from created to executing. The sequence is fixed; no model plans it."""
        case = state["case"]
        self._record(AuditEventType.CASE_CREATED, case, f"alert {case.alert.id}")
        case, moved = self._move(case, CaseStatus.PLANNING, CaseStatus.EXECUTING)
        return {"case": case, "trail": moved}

    def gather(self, state: CaseGraphState) -> Update:
        """Run the data agent to fetch the records."""
        return self._guarded(lambda s: {"dossier": self._agents.data.gather(s["case"])})(state)

    def analyze(self, state: CaseGraphState) -> Update:
        """Run the analysis agent to compute the findings."""

        def step(s: CaseGraphState) -> Update:
            if self._agents.agentic is not None:
                outcome = self._agents.agentic.analyze(s["case"], s["dossier"])
                return {"findings": list(outcome.findings), "inquiry": outcome.report}
            found = self._agents.analysis.analyze(s["case"], s["dossier"])
            return {"findings": list(found)}

        update = self._guarded(step)(state)
        report = update.get("inquiry")
        if isinstance(report, InquiryReport):
            self._record(AuditEventType.EVIDENCE_RECORDED, state["case"], report.audit_line())
        return update

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
        issues = sorted({i.code.value for i in state["verification"].issues if i.code in BLOCKING})
        code = "validation:" + ",".join(issues)
        return self._stop(state["case"], CaseStatus.FAILED_VALIDATION, code)

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
            return self._stop(case, CaseStatus.BLOCKED_BY_POLICY, problem)
        case = case.model_copy(update={"decision_id": decision.id})
        self._record(
            AuditEventType.DECISION_MADE,
            case,
            decision.recommended_action.value,
            decision_id=decision.id,
        )
        return {"case": case, "decision": decision}

    def request_approval(self, state: CaseGraphState) -> Update:
        """Build the approval request from the approval matrix and move to waiting_for_approval."""
        case, decision = state["case"], state["decision"]
        rule = approval_rule_for(decision.recommended_action)
        if rule is None:  # a Level 3+ action with no matrix entry: refuse rather than guess
            return self._stop(case, CaseStatus.BLOCKED_BY_POLICY, "approval:no_rule")
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
        if self._approvals is not None:
            self._approvals.add_request(request)
        case, moved = self._move(case, CaseStatus.WAITING_FOR_APPROVAL)
        self._record(
            AuditEventType.APPROVAL_REQUESTED,
            case,
            request.id,
            decision_id=decision.id,
            approval_status=ApprovalStatus.PENDING,
        )
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
        votes = [ApprovalVote.model_validate(v) for v in received]
        for vote in votes:
            self._record(
                AuditEventType.APPROVAL_VOTE_CAST,
                state["case"],
                f"{request.id}:{vote.role.value}:{vote.verdict.value}",
                reviewer_id=vote.approver_id,
            )
        return {"votes": votes, "rounds": state.get("rounds", 0) + 1}

    def settle(self, state: CaseGraphState) -> Update:
        """Apply the pure approval rule to the votes; still pending means wait for more."""
        request = state["approval_request"]
        if self._approvals is not None:  # the store mirrors every vote received so far
            self._approvals.set_votes(request.id, state.get("votes", []))
        status = evaluate_approval(request, state.get("votes", []), self._clock())
        target = {
            ApprovalStatus.APPROVED: CaseStatus.APPROVED,
            ApprovalStatus.REJECTED: CaseStatus.REJECTED_BY_HUMAN,
            ApprovalStatus.ESCALATED: CaseStatus.ESCALATED,
            ApprovalStatus.EXPIRED: CaseStatus.TIMED_OUT,
            # A reviewer who wants the action changed hands the case to an analyst: nothing runs.
            ApprovalStatus.MODIFICATION_REQUESTED: CaseStatus.ESCALATED,
        }.get(status)
        if target is None:  # still pending, unless humans have already been asked too often
            if state.get("rounds", 0) >= self._limits.max_vote_rounds:
                stopped = self._stop(
                    state["case"], CaseStatus.ESCALATED, "approval:too_many_rounds"
                )
                return {**stopped, "approval": status}
            return {"approval": status}
        case, moved = self._move(state["case"], target)
        return {"case": case, "trail": moved, "approval": status}

    # --- carrying out the action (6d) --------------------------------------------------------
    def act(self, state: CaseGraphState) -> Update:
        """Carry out a Level 1-2 recommendation. Policy needs no approval for these, so say so.

        The case goes decision_ready -> approved by policy (no human is involved), then through the
        same guarded tool, verification and completion as an approved action.
        """
        assert self._registry is not None  # the graph only has this step when execution is enabled
        case, decision = state["case"], state["decision"]
        case, moved = self._move(case, CaseStatus.APPROVED)
        level = int(decision.risk_level)
        self._record(AuditEventType.STATE_CHANGED, case, f"policy:no_approval_needed_level_{level}")
        return self._carry_out(
            case, moved, decision.recommended_action, case.alert.account_id, approval_id=None
        )

    def execute(self, state: CaseGraphState) -> Update:
        """Apply the approved action through the guarded tool, check it took effect, and finish.

        The approval id is the only authority: the tool re-verifies action, account, case,
        approvers, expiry and single use itself. A refusal ends the case ``FAILED_TOOL``; an action
        that did not take effect ends it ``FAILED_VALIDATION``.
        """
        request = state["approval_request"]
        return self._carry_out(
            state["case"], [], request.action, request.target_account_id, approval_id=request.id
        )

    def _carry_out(
        self,
        case: Case,
        prior: list[CaseStatus],
        action: ActionType,
        account_id: str,
        *,
        approval_id: str | None,
    ) -> Update:
        """Run ``action`` through the tool that owns it, confirm its effect, and close the case."""
        assert self._registry is not None
        tool = EXECUTE_TOOL if action in EXECUTABLE_ACTIONS else PERFORM_TOOL
        result = self._registry.invoke(
            ToolCall(
                id=f"{case.id}:execute",
                tool_name=tool,
                actor=EXECUTOR,
                case_id=case.id,
                arguments={"account_id": account_id, "action": action.value},
                approval_id=approval_id,
                requested_at=self._clock(),
            )
        )
        if not result.ok:
            stopped = self._stop(case, CaseStatus.FAILED_TOOL, f"{tool}:{result.error_code}")
            return {**stopped, "trail": [*prior, *stopped["trail"]]}  # type: ignore[misc]
        case, moved = self._move(case, CaseStatus.EXECUTED)
        if action is ActionType.FREEZE_ACCOUNT:
            took_effect = result.output.get("account_status") == "frozen"
        elif action is ActionType.BLOCK_CARD:
            took_effect = result.output.get("card_status") == "blocked"
        else:
            took_effect = result.output.get("recorded") == action.value
        if not took_effect:
            stopped = self._stop(case, CaseStatus.FAILED_VALIDATION, "execution:not_applied")
            return {**stopped, "trail": [*prior, *moved, *stopped["trail"]]}  # type: ignore[misc]
        case, done = self._move(case, CaseStatus.VERIFIED, CaseStatus.COMPLETED)
        return {"case": case, "trail": [*prior, *moved, *done]}
