"""The authorization rules: roles, case scope and the approval gate."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from nexa.domain.actions import ActionType
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.security import (
    AuthorizationDecision,
    AuthorizationDenied,
    CaseScope,
    DenialReason,
    authorize_role,
    check_scope,
    verify_execution_approval,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def agent(role: Role = Role.DATA_AGENT) -> Actor:
    return Actor(kind=ActorKind.AGENT, id="agent_1", role=role)


# --- decisions ---------------------------------------------------------
def test_decision_requires_a_reason_exactly_when_denied() -> None:
    assert AuthorizationDecision.allow().allowed
    assert AuthorizationDecision.deny(DenialReason.NO_ROLE).reason is DenialReason.NO_ROLE
    with pytest.raises(ValidationError):
        AuthorizationDecision(allowed=False)
    with pytest.raises(ValidationError):
        AuthorizationDecision(allowed=True, reason=DenialReason.NO_ROLE)


def test_raise_if_denied() -> None:
    AuthorizationDecision.allow().raise_if_denied()
    with pytest.raises(AuthorizationDenied) as caught:
        AuthorizationDecision.deny(DenialReason.OUT_OF_SCOPE, "nope").raise_if_denied()
    assert caught.value.reason is DenialReason.OUT_OF_SCOPE


# --- roles -------------------------------------------------------------
def test_listed_role_is_allowed_and_others_are_denied() -> None:
    allowed = {Role.DATA_AGENT}
    assert authorize_role(agent(Role.DATA_AGENT), allowed).allowed
    denied = authorize_role(agent(Role.ANALYSIS_AGENT), allowed)
    assert denied.reason is DenialReason.ROLE_NOT_PERMITTED


def test_actor_without_a_role_is_always_denied() -> None:
    nobody = Actor(kind=ActorKind.SYSTEM, id="sys")
    assert authorize_role(nobody, set(Role)).reason is DenialReason.NO_ROLE


def test_empty_allow_list_denies_everyone() -> None:
    assert not authorize_role(agent(), set()).allowed


# --- scope -------------------------------------------------------------
class FakeScopes:
    def __init__(self) -> None:
        self.scope = CaseScope(case_id="case_1", customer_id="cust_1", account_ids=("acc_1",))

    def get_scope(self, case_id: str) -> CaseScope | None:
        return self.scope if case_id == "case_1" else None


def test_agent_may_touch_its_own_cases_records() -> None:
    scopes = FakeScopes()
    assert check_scope(scopes, agent(), "case_1", customer_id="cust_1", account_id="acc_1").allowed


@pytest.mark.parametrize(
    ("case_id", "customer_id", "account_id", "reason"),
    [
        (None, "cust_1", None, DenialReason.CASE_REQUIRED),
        ("case_missing", "cust_1", None, DenialReason.OUT_OF_SCOPE),
        ("case_1", "cust_2", None, DenialReason.OUT_OF_SCOPE),
        ("case_1", None, "acc_2", DenialReason.OUT_OF_SCOPE),
    ],
)
def test_agent_cannot_leave_its_case(
    case_id: str | None, customer_id: str | None, account_id: str | None, reason: DenialReason
) -> None:
    decision = check_scope(
        FakeScopes(), agent(), case_id, customer_id=customer_id, account_id=account_id
    )
    assert decision.reason is reason


def test_human_investigators_are_not_scope_limited_here() -> None:
    human = Actor(kind=ActorKind.USER, id="u1", role=Role.FRAUD_ANALYST)
    assert check_scope(FakeScopes(), human, None, account_id="anything").allowed


# --- approval gate -----------------------------------------------------
class FakeApprovals:
    def __init__(self, request: ApprovalRequest | None, votes: list[ApprovalVote]) -> None:
        self.request = request
        self.votes = votes
        self.used: set[str] = set()

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        return self.request if self.request and self.request.id == approval_id else None

    def get_votes(self, approval_id: str) -> list[ApprovalVote]:
        return self.votes

    def try_consume(self, approval_id: str) -> bool:
        if approval_id in self.used:
            return False
        self.used.add(approval_id)
        return True


def freeze_request(**overrides: object) -> ApprovalRequest:
    fields: dict[str, object] = {
        "id": "apr_1",
        "case_id": "case_1",
        "decision_id": "dec_1",
        "target_account_id": "acc_1",
        "action": ActionType.FREEZE_ACCOUNT,
        "risk_level": 4,
        "required_roles": (Role.FRAUD_ANALYST, Role.RISK_OFFICER),
        "requested_at": NOW - timedelta(minutes=30),
        "expires_at": NOW + timedelta(minutes=30),
    }
    fields.update(overrides)
    return ApprovalRequest(**fields)  # type: ignore[arg-type]


def approving_votes() -> list[ApprovalVote]:
    when = NOW - timedelta(minutes=10)
    return [
        ApprovalVote(
            request_id="apr_1", approver_id="ana", role=Role.FRAUD_ANALYST,
            verdict=Verdict.APPROVE, decided_at=when,
        ),
        ApprovalVote(
            request_id="apr_1", approver_id="raj", role=Role.RISK_OFFICER,
            verdict=Verdict.APPROVE, decided_at=when,
        ),
    ]  # fmt: skip


def gate(
    source: FakeApprovals,
    *,
    approval_id: str | None = "apr_1",
    action: ActionType = ActionType.FREEZE_ACCOUNT,
    case_id: str | None = "case_1",
    account_id: str = "acc_1",
    now: datetime = NOW,
) -> AuthorizationDecision:
    return verify_execution_approval(
        source, approval_id=approval_id, action=action, case_id=case_id,
        account_id=account_id, now=now,
    )  # fmt: skip


def test_fully_approved_request_passes_the_gate() -> None:
    assert gate(FakeApprovals(freeze_request(), approving_votes())).allowed


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"approval_id": None}, DenialReason.APPROVAL_REQUIRED),
        ({"approval_id": "apr_missing"}, DenialReason.APPROVAL_NOT_FOUND),
        ({"action": ActionType.BLOCK_CARD}, DenialReason.APPROVAL_MISMATCH),
        ({"case_id": "case_other"}, DenialReason.APPROVAL_MISMATCH),
        ({"account_id": "acc_other"}, DenialReason.APPROVAL_MISMATCH),
        ({"now": NOW + timedelta(hours=2)}, DenialReason.APPROVAL_NOT_APPROVED),
    ],
)
def test_gate_denies_anything_that_does_not_match_the_approval(
    kwargs: dict[str, object], reason: DenialReason
) -> None:
    decision = gate(FakeApprovals(freeze_request(), approving_votes()), **kwargs)  # type: ignore[arg-type]
    assert decision.reason is reason


def test_gate_denies_when_a_required_role_has_not_approved() -> None:
    only_analyst = approving_votes()[:1]
    decision = gate(FakeApprovals(freeze_request(), only_analyst))
    assert decision.reason is DenialReason.APPROVAL_NOT_APPROVED
    assert "pending" in decision.detail


def test_gate_denies_after_a_rejection() -> None:
    votes = approving_votes()
    votes.append(
        ApprovalVote(
            request_id="apr_1", approver_id="cat", role=Role.COMPLIANCE_OFFICER,
            verdict=Verdict.REJECT, decided_at=NOW - timedelta(minutes=5),
        )
    )  # fmt: skip
    assert not gate(FakeApprovals(freeze_request(), votes)).allowed
