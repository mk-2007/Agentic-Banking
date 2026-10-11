"""Shared fixtures: a real registry over the synthetic bank, with fake scopes and approvals."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from nexa.audit import AuditRecorder, InMemoryAuditLog
from nexa.bank_sim import InMemoryBank, load_bank
from nexa.domain.actions import ActionType
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.domain.tooling import ToolCall
from nexa.security import CaseScope
from nexa.tools import ToolContext, ToolRegistry, build_default_registry

NOW = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


class FakeScopes:
    """Case management stand-in: case_f is the account-takeover case on acc_106."""

    def __init__(self) -> None:
        self._scopes = {
            "case_f": CaseScope(case_id="case_f", customer_id="cust_106", account_ids=("acc_106",)),
            "case_b": CaseScope(case_id="case_b", customer_id="cust_102", account_ids=("acc_102",)),
        }

    def add(self, scope: CaseScope) -> None:
        self._scopes[scope.case_id] = scope

    def get_scope(self, case_id: str) -> CaseScope | None:
        return self._scopes.get(case_id)


class FakeApprovals:
    """In-memory approval store implementing the ApprovalSource protocol."""

    def __init__(self) -> None:
        self.requests: dict[str, ApprovalRequest] = {}
        self.votes: dict[str, list[ApprovalVote]] = {}
        self.used: set[str] = set()

    def add(self, request: ApprovalRequest, votes: Sequence[ApprovalVote]) -> None:
        self.requests[request.id] = request
        self.votes[request.id] = list(votes)

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        return self.requests.get(approval_id)

    def get_votes(self, approval_id: str) -> Sequence[ApprovalVote]:
        return self.votes.get(approval_id, [])

    def try_consume(self, approval_id: str) -> bool:
        if approval_id in self.used:
            return False
        self.used.add(approval_id)
        return True


class Env:
    """Everything a test needs, wired together."""

    def __init__(self) -> None:
        self.bank: InMemoryBank = load_bank()
        self.log = InMemoryAuditLog()
        self.approvals = FakeApprovals()
        self.now = NOW
        self.scopes = FakeScopes()
        self.ctx = ToolContext(
            bank=self.bank,
            scopes=self.scopes,
            approvals=self.approvals,
            audit=AuditRecorder(self.log, clock=lambda: self.now),
            clock=lambda: self.now,
        )
        self.registry: ToolRegistry = build_default_registry(self.ctx)
        self._counter = 0

    def call(
        self,
        tool: str,
        actor: Actor,
        arguments: dict[str, str | int | float | bool | None] | None = None,
        *,
        case_id: str | None = "case_f",
        approval_id: str | None = None,
    ) -> ToolCall:
        self._counter += 1
        return ToolCall(
            id=f"call_{self._counter}", tool_name=tool, actor=actor, case_id=case_id,
            arguments=arguments or {}, approval_id=approval_id, requested_at=self.now,
        )  # fmt: skip

    def freeze_approval(
        self, approval_id: str = "apr_1", *, account: str = "acc_106", case: str = "case_f"
    ) -> str:
        """Create a fully approved Level 4 freeze approval and return its id."""
        request = ApprovalRequest(
            id=approval_id, case_id=case, decision_id="dec_1", target_account_id=account,
            action=ActionType.FREEZE_ACCOUNT, risk_level=4,
            required_roles=(Role.FRAUD_ANALYST, Role.RISK_OFFICER),
            requested_at=self.now - timedelta(minutes=20),
            expires_at=self.now + timedelta(minutes=40),
        )  # fmt: skip
        when = self.now - timedelta(minutes=5)
        self.approvals.add(
            request,
            [
                ApprovalVote(request_id=approval_id, approver_id="ana", role=Role.FRAUD_ANALYST,
                             verdict=Verdict.APPROVE, decided_at=when),
                ApprovalVote(request_id=approval_id, approver_id="raj", role=Role.RISK_OFFICER,
                             verdict=Verdict.APPROVE, decided_at=when),
            ],
        )  # fmt: skip
        return approval_id


def agent(role: Role) -> Actor:
    return Actor(kind=ActorKind.AGENT, id=f"{role.value}_1", role=role)


def human(role: Role) -> Actor:
    return Actor(kind=ActorKind.USER, id=f"{role.value}_u1", role=role)


EXECUTOR = Actor(kind=ActorKind.SYSTEM, id="executor", role=Role.EXECUTION_SERVICE)


@pytest.fixture
def env() -> Env:
    return Env()
