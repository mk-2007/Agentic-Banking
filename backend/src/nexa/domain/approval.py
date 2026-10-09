"""Human approval: requests, votes, and the rule that turns votes into a status.

`evaluate_approval` is a pure function. The same votes always give the same answer, and it
needs no database, which makes the rule easy to test and to audit.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .actions import ActionType, RiskLevel, risk_level_for
from .actors import APPROVER_ROLES, Role
from .base import Contract


class Verdict(StrEnum):
    """What a human reviewer decides (PRD section 13)."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    ESCALATE = "escalate"


class ApprovalStatus(StrEnum):
    """Overall state of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFICATION_REQUESTED = "modification_requested"
    ESCALATED = "escalated"
    EXPIRED = "expired"


class ApprovalRequest(Contract):
    """A request for humans to authorize one action."""

    id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    action: ActionType
    risk_level: RiskLevel
    required_roles: tuple[Role, ...] = Field(min_length=1)
    requested_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def check_request(self) -> Self:
        """Only Level 3+ actions need approval; Level 4 needs two different roles."""
        if self.risk_level != risk_level_for(self.action):
            raise ValueError("risk_level does not match the action")
        if not self.risk_level.requires_human_approval:
            raise ValueError("only Level 3 and Level 4 actions need an approval request")
        if len(set(self.required_roles)) != len(self.required_roles):
            raise ValueError("required_roles must be unique")
        if not set(self.required_roles) <= APPROVER_ROLES:
            raise ValueError("required_roles must be bank approver roles")
        if self.risk_level is RiskLevel.HIGH_RISK and len(self.required_roles) < 2:
            raise ValueError("Level 4 actions need at least two different approver roles")
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        return self


class ApprovalVote(Contract):
    """One human's verdict on an approval request."""

    request_id: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    role: Role
    verdict: Verdict
    comment: str = ""
    decided_at: AwareDatetime


def evaluate_approval(
    request: ApprovalRequest, votes: Sequence[ApprovalVote], now: AwareDatetime
) -> ApprovalStatus:
    """Decide the status of ``request`` from the votes cast so far.

    Rules:
    - Only votes for this request, by human approver roles, cast inside the
      request's time window, are counted. Each approver counts once (latest vote wins).
    - Any reject, escalate or modify vote ends the matter, in that order of precedence.
    - Approval needs an approve vote from every required role, from different people,
      and only counts while the request has not expired.
    """
    latest: dict[str, ApprovalVote] = {}
    for vote in sorted(votes, key=lambda v: v.decided_at):
        in_window = request.requested_at <= vote.decided_at < request.expires_at
        if vote.request_id == request.id and vote.role in APPROVER_ROLES and in_window:
            latest[vote.approver_id] = vote

    verdicts = {v.verdict for v in latest.values()}
    if Verdict.REJECT in verdicts:
        return ApprovalStatus.REJECTED
    if Verdict.ESCALATE in verdicts:
        return ApprovalStatus.ESCALATED
    if Verdict.MODIFY in verdicts:
        return ApprovalStatus.MODIFICATION_REQUESTED

    approved_roles = {v.role for v in latest.values() if v.verdict is Verdict.APPROVE}
    expired = now >= request.expires_at
    if set(request.required_roles) <= approved_roles:
        return ApprovalStatus.EXPIRED if expired else ApprovalStatus.APPROVED
    return ApprovalStatus.EXPIRED if expired else ApprovalStatus.PENDING
