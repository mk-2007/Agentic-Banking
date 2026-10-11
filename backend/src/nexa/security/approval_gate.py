"""The gate between an approval and the execution of the action it authorizes.

An approval authorizes exactly one thing: one action, on one account, for one case, once, and
only until it expires. `verify_execution_approval` checks every one of those conditions with the
domain's `evaluate_approval` rule. Passing it is necessary for execution; the execution tool
then consumes the approval so it cannot be replayed.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import AwareDatetime

from nexa.domain.actions import ActionType
from nexa.domain.approval import ApprovalRequest, ApprovalStatus, ApprovalVote, evaluate_approval

from .decisions import AuthorizationDecision, DenialReason


class ApprovalSource(Protocol):
    """Where approvals live (implemented by the approvals package in a later phase)."""

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Return the approval request, or None if it does not exist."""
        ...

    def get_votes(self, approval_id: str) -> Sequence[ApprovalVote]:
        """Return every vote cast on the request."""
        ...

    def try_consume(self, approval_id: str) -> bool:
        """Mark the approval used. Return False if it was already used (atomic)."""
        ...


def verify_execution_approval(
    source: ApprovalSource,
    *,
    approval_id: str | None,
    action: ActionType,
    case_id: str | None,
    account_id: str,
    now: AwareDatetime,
) -> AuthorizationDecision:
    """Decide whether ``approval_id`` currently authorizes ``action`` on ``account_id``."""
    if not approval_id:
        return AuthorizationDecision.deny(DenialReason.APPROVAL_REQUIRED, "no approval id given")
    request = source.get_request(approval_id)
    if request is None:
        return AuthorizationDecision.deny(DenialReason.APPROVAL_NOT_FOUND)
    if request.action != action:
        return AuthorizationDecision.deny(
            DenialReason.APPROVAL_MISMATCH, "approval is for a different action"
        )
    if request.case_id != case_id:
        return AuthorizationDecision.deny(
            DenialReason.APPROVAL_MISMATCH, "approval belongs to a different case"
        )
    if request.target_account_id != account_id:
        return AuthorizationDecision.deny(
            DenialReason.APPROVAL_MISMATCH, "approval is for a different account"
        )
    status = evaluate_approval(request, source.get_votes(approval_id), now)
    if status is not ApprovalStatus.APPROVED:
        return AuthorizationDecision.deny(
            DenialReason.APPROVAL_NOT_APPROVED, f"approval status is {status.value}"
        )
    return AuthorizationDecision.allow()
