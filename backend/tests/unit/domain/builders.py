"""Small factory helpers so each test only states what it cares about."""

from datetime import UTC, datetime, timedelta

from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.domain.case import Alert, Case
from nexa.domain.decision import CandidateScore, Decision, UncertaintyFlag
from nexa.domain.evidence import PolicyRef

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
POLICY = PolicyRef(doc_id="fraud-policy", version="1.0", section="4.2")


def minutes(n: int) -> datetime:
    """Return NOW shifted by ``n`` minutes."""
    return NOW + timedelta(minutes=n)


def make_case(**overrides: object) -> Case:
    """Build a valid case in CREATED state."""
    alert = Alert(
        id="alert_1",
        transaction_id="txn_1",
        account_id="acc_1",
        customer_id="cust_1",
        trigger="velocity_rule",
        raised_at=NOW,
    )
    fields: dict[str, object] = {
        "id": "case_1",
        "alert": alert,
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Case(**fields)  # type: ignore[arg-type]


def make_decision(
    action: ActionType = ActionType.ESCALATE_TO_ANALYST,
    *,
    ranked: tuple[CandidateScore, ...] | None = None,
    flags: tuple[UncertaintyFlag, ...] = (),
    overridden_by: str | None = None,
    policy_refs: tuple[PolicyRef, ...] = (POLICY,),
    supporting: tuple[str, ...] = ("ev_1",),
) -> Decision:
    """Build a decision recommending ``action``; override pieces to test invariants."""
    risk = risk_level_for(action)
    other = (
        ActionType.NO_ACTION if action is not ActionType.NO_ACTION else ActionType.MONITOR_ACCOUNT
    )
    candidates = ranked or (
        CandidateScore(action=action, score=0.9, supporting_evidence_ids=supporting),
        CandidateScore(action=other, score=0.1),
    )
    return Decision(
        id="dec_1",
        case_id="case_1",
        ranked_candidates=candidates,
        recommended_action=action,
        overridden_by=overridden_by,
        risk_level=risk,
        approval_required=risk.requires_human_approval,
        uncertainty_flags=flags,
        evidence_strength=0.8,
        policy_refs=policy_refs,
        provider="rule_scorer",
        created_at=NOW,
    )


def make_request(
    action: ActionType = ActionType.FREEZE_ACCOUNT,
    roles: tuple[Role, ...] = (Role.FRAUD_ANALYST, Role.RISK_OFFICER),
) -> ApprovalRequest:
    """Build an approval request valid for ``action`` (expires 60 minutes after NOW)."""
    return ApprovalRequest(
        id="apr_1",
        case_id="case_1",
        decision_id="dec_1",
        action=action,
        risk_level=risk_level_for(action),
        required_roles=roles,
        requested_at=NOW,
        expires_at=minutes(60),
    )


def vote(approver: str, role: Role, verdict: Verdict, at_minute: int = 5) -> ApprovalVote:
    """Build a vote on request ``apr_1``."""
    return ApprovalVote(
        request_id="apr_1",
        approver_id=approver,
        role=role,
        verdict=verdict,
        decided_at=minutes(at_minute),
    )


def human(role: Role = Role.FRAUD_ANALYST, ident: str = "u_1") -> Actor:
    """Build a human actor."""
    return Actor(kind=ActorKind.USER, id=ident, role=role)
