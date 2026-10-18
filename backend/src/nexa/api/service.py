"""The case service: wires the platform together once and runs cases for the API.

It holds no policy of its own. Cases run through the same graph the evaluations use, votes are
judged by the pure approval rule, and execution goes through the guarded tool. What lives here is
plumbing: building the world, keeping the latest run of each case, and serialising access (the
graph, the approval store and the audit log are shared and the prototype keeps them in memory).
"""

import threading
from dataclasses import dataclass
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver

from nexa.agents.base import AgentContext
from nexa.approvals import InMemoryApprovalStore
from nexa.audit import AuditRecorder, InMemoryAuditLog
from nexa.bank_sim import load_bank
from nexa.bank_sim.gateway import BankGateway
from nexa.config import effective_clearance
from nexa.decision import DecisionProvider, RuleBasedDecisionProvider
from nexa.domain.actors import Actor, ActorKind, Role, SessionChannel
from nexa.domain.approval import ApprovalVote, Verdict
from nexa.domain.audit import AuditEvent
from nexa.domain.case import Alert, Case
from nexa.domain.clock import Clock, utc_now
from nexa.domain.ids import new_id
from nexa.domain.tooling import ToolCall
from nexa.llm import LlmGateway
from nexa.orchestration import (
    CaseGraph,
    CaseRun,
    build_case_graph,
    checkpoint_serde,
    provider_source,
    resume_case,
    run_case,
)
from nexa.rag import KnowledgeSearch, load_knowledge_base
from nexa.security import CaseScope
from nexa.tools import ToolContext, build_default_registry

from .principals import Principal

CHATBOT = Actor(kind=ActorKind.AGENT, id="chatbot_1", role=Role.CUSTOMER_SERVICE_AGENT)


class CaseNotFoundError(LookupError):
    """No case has this id."""


class NotWaitingError(ValueError):
    """The case is not waiting for approval, so it cannot take votes."""


class InvalidAlertError(ValueError):
    """The alert does not match the bank's records."""


class _Scopes:
    """Which records each case may touch, set when the case is opened."""

    def __init__(self) -> None:
        self.scopes: dict[str, CaseScope] = {}

    def get_scope(self, case_id: str) -> CaseScope | None:
        return self.scopes.get(case_id)


@dataclass(frozen=True)
class Passage:
    """One cited passage returned by chat."""

    title: str
    document_id: str
    version: str
    section: str
    text: str


class CaseService:
    """Opens cases, takes votes and answers questions, all through the platform's layers."""

    def __init__(
        self,
        *,
        bank: BankGateway | None = None,
        knowledge: KnowledgeSearch | None = None,
        provider: DecisionProvider | None = None,
        gateway: LlmGateway | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._clock = clock
        self._scopes = _Scopes()
        self.approvals = InMemoryApprovalStore()
        self.log = InMemoryAuditLog()
        self.bank = bank or load_bank()
        tools = ToolContext(
            bank=self.bank,
            scopes=self._scopes,
            approvals=self.approvals,
            knowledge=knowledge or load_knowledge_base(),
            audit=AuditRecorder(self.log, clock=clock),
            clock=clock,
        )
        self._registry = build_default_registry(tools)
        # Investigations serve employees; the channel is set here, by trusted code.
        self._ctx = AgentContext(
            registry=self._registry,
            clock=clock,
            channel=SessionChannel.EMPLOYEE,
            gateway=gateway,
        )
        decider = provider or RuleBasedDecisionProvider(clock)
        self._graph: CaseGraph = build_case_graph(
            self._ctx,
            checkpointer=MemorySaver(serde=checkpoint_serde()),
            decide=provider_source(decider),
            audit=AuditRecorder(self.log, clock=clock),
            approvals=self.approvals,
        )
        self._runs: dict[str, CaseRun] = {}
        self._lock = threading.Lock()

    def now(self) -> datetime:
        """Return the service's current time (the clock cases and approvals use)."""
        return self._clock()

    # --- cases -----------------------------------------------------------------------------
    def open_case(
        self, *, account_id: str, customer_id: str, transaction_id: str, trigger: str
    ) -> CaseRun:
        """Check the alert against the bank's records, open a case and run it."""
        transaction = self.bank.get_transaction(transaction_id)
        account = self.bank.get_account(account_id)
        if transaction.account_id != account_id or account.customer_id != customer_id:
            raise InvalidAlertError("the transaction, account and customer do not belong together")
        now = self._clock()
        alert = Alert(
            id=new_id("alert"),
            transaction_id=transaction_id,
            account_id=account_id,
            customer_id=customer_id,
            trigger=trigger,
            raised_at=now,
        )
        case = Case(id=new_id("case"), alert=alert, created_at=now, updated_at=now)
        with self._lock:
            self._scopes.scopes[case.id] = CaseScope(
                case_id=case.id, customer_id=customer_id, account_ids=(account_id,)
            )
            run = run_case(case, self._ctx, graph=self._graph, thread_id=case.id)
            self._runs[case.id] = run
        return run

    def _sweep(self) -> None:
        """Time out cases whose approval ran out while nobody voted. Call with the lock held.

        The approval rule only runs when votes arrive, so without this a case nobody votes on would
        wait forever. Resuming with no votes lets the same rule see that the request has expired.
        """
        now = self._clock()
        for case_id, run in list(self._runs.items()):
            request = run.approval_request
            if run.awaiting_approval and request is not None and now >= request.expires_at:
                self._runs[case_id] = resume_case(self._graph, case_id, [])

    def get(self, case_id: str) -> CaseRun:
        """Return the latest run of a case."""
        with self._lock:
            self._sweep()
            if case_id not in self._runs:
                raise CaseNotFoundError(case_id)
            return self._runs[case_id]

    def all_runs(self) -> list[CaseRun]:
        """Every case, oldest first."""
        with self._lock:
            self._sweep()
            return list(self._runs.values())

    def pending(self) -> list[CaseRun]:
        """Cases paused for human votes."""
        return [run for run in self.all_runs() if run.awaiting_approval]

    def vote(self, case_id: str, who: Principal, verdict: Verdict, comment: str = "") -> CaseRun:
        """Record ``who``'s verdict and continue the case. Identity and role come from ``who``."""
        with self._lock:
            run = self._runs.get(case_id)
            if run is None:
                raise CaseNotFoundError(case_id)
            if not run.awaiting_approval or run.approval_request is None:
                raise NotWaitingError(f"case {case_id} is not waiting for approval")
            ballot = ApprovalVote(
                request_id=run.approval_request.id,
                approver_id=who.user_id,
                role=who.role,
                verdict=verdict,
                comment=comment,
                decided_at=self._clock(),
            )
            run = resume_case(self._graph, case_id, [ballot])
            self._runs[case_id] = run
            return run

    def audit(self, case_id: str) -> tuple[AuditEvent, ...]:
        """Return the audit chain for one case."""
        self.get(case_id)  # unknown cases are a 404, not an empty list
        return self.log.for_case(case_id)

    # --- chat ------------------------------------------------------------------------------
    def chat(self, question: str, who: Principal) -> tuple[Passage, ...]:
        """Answer from the knowledge base, with clearance set by the caller's role and channel.

        A customer is served by the chatbot (the customer-service agent: public knowledge only).
        An employee asks as themselves, with their own role's permissions. Either way the call goes
        through the tool layer, so permissions and audit apply, and the channel comes from the
        authenticated principal, never from the request.
        """
        actor = (
            Actor(kind=ActorKind.USER, id=who.user_id, role=who.role)
            if who.is_employee
            else CHATBOT
        )
        if actor.role is None or effective_clearance(actor.role, who.channel) is None:
            return ()
        result = self._registry.invoke(
            ToolCall(
                id=new_id("chat"),
                tool_name="search_knowledge_base",
                actor=actor,
                case_id=f"chat_{who.user_id}",  # agents must name a case; a conversation will do
                arguments={"query": question, "top_k": 3},
                channel=who.channel,
                requested_at=self._clock(),
            )
        )
        if not result.ok:
            return ()
        raw = result.output.get("results")
        hits = raw if isinstance(raw, list) else []
        return tuple(
            Passage(
                title=str(hit.get("title", "")),
                document_id=str(hit.get("document_id", "")),
                version=str(hit.get("version", "")),
                section=str(hit.get("section", "")),
                text=str(hit.get("text", "")),
            )
            for hit in hits
            if isinstance(hit, dict)
        )
