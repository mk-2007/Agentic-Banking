"""The one tool that changes the bank, and the checks that guard it.

`execute_authorized_action` refuses to run unless a valid approval is presented: right action, right
account, right case, enough approvers, not expired, never used before. It is callable only by the
execution service. This is the code-level guarantee behind "agents recommend, humans authorize".
"""

import time
from collections.abc import Callable
from typing import ClassVar, TypeVar

from pydantic import Field

from nexa.config import roles_for
from nexa.domain.actions import ActionType, RiskLevel
from nexa.domain.approval import ApprovalStatus
from nexa.domain.audit import AuditEventType
from nexa.domain.base import Contract, JsonDict
from nexa.domain.errors import DomainError
from nexa.domain.tooling import ToolCall, ToolSpec
from nexa.security import AuthorizationDecision, DenialReason, verify_execution_approval

from .base import Tool, ToolContext

NAME = "execute_authorized_action"
FAILED_PREFIX = (
    "exec_failed"  # output_ref of the audit event written when the bank never applied it
)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.05  # shortcut: fixed small delay; use exponential backoff against a real bank

T = TypeVar("T")


class TransientBankError(DomainError):
    """The bank could not be reached or timed out; the same request may be tried again."""


EXECUTABLE_ACTIONS = frozenset({ActionType.BLOCK_CARD, ActionType.FREEZE_ACCOUNT})


class _ExecuteArgs(Contract):
    account_id: str = Field(min_length=1)
    action: ActionType


def consume_approval(call: ToolCall, ctx: ToolContext, action: ActionType, account_id: str) -> str:
    """Check the call's approval authorizes ``action`` on ``account_id``, spend it, return its id.

    Raises `AuthorizationDenied` when there is no approval, it does not fit, or it was used before.
    """
    approval_id = call.approval_id
    if approval_id is None:
        AuthorizationDecision.deny(
            DenialReason.APPROVAL_REQUIRED, "no approval id given"
        ).raise_if_denied()
        raise AssertionError("unreachable")  # raise_if_denied always raises for a denial

    verify_execution_approval(
        ctx.approvals,
        approval_id=approval_id,
        action=action,
        case_id=call.case_id,
        account_id=account_id,
        now=ctx.clock(),
    ).raise_if_denied()

    if not ctx.approvals.try_consume(approval_id):
        AuthorizationDecision.deny(
            DenialReason.APPROVAL_ALREADY_USED, "an approval can be used only once"
        ).raise_if_denied()
    return approval_id


def apply_with_retry(apply: Callable[[], T], *, sleep: Callable[[float], None] = time.sleep) -> T:
    """Call the bank, retrying a transient failure a bounded number of times.

    Freeze and block are idempotent on the bank, so repeating a request whose outcome is unknown is
    safe. After ``MAX_ATTEMPTS`` the last error is raised.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return apply()
        except TransientBankError:
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")


class ExecuteAuthorizedAction(Tool):
    """Apply an approved block-card or freeze-account action."""

    spec: ClassVar[ToolSpec] = ToolSpec(
        name=NAME,
        description="Apply an approved action to an account. Requires a valid approval id.",
        risk_level=RiskLevel.HIGH_RISK,
        required_roles=roles_for(NAME),
        read_only=False,
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Verify the approval, consume it, then apply the action."""
        args = _ExecuteArgs.model_validate(call.arguments)
        if args.action not in EXECUTABLE_ACTIONS:
            AuthorizationDecision.deny(
                DenialReason.UNSUPPORTED_ACTION, f"{args.action.value} is not executable here"
            ).raise_if_denied()

        approval_id = consume_approval(call, ctx, args.action, args.account_id)

        apply = (
            ctx.bank.freeze_account
            if args.action is ActionType.FREEZE_ACCOUNT
            else ctx.bank.block_card
        )
        try:
            account = apply_with_retry(lambda: apply(args.account_id))
        except TransientBankError:
            # The approval is already spent, so leave a record that reconciliation reports to
            # operations: a human decides whether to ask for a fresh approval.
            ctx.audit.record(
                AuditEventType.ERROR,
                call.actor,
                case_id=call.case_id,
                tool_name=NAME,
                output_ref=f"{FAILED_PREFIX}:{args.action.value}:{args.account_id}:{approval_id}",
                detail=f"bank unavailable after {MAX_ATTEMPTS} attempts; nothing applied",
            )
            raise

        ctx.audit.record(
            AuditEventType.ACTION_EXECUTED,
            call.actor,
            case_id=call.case_id,
            tool_name=NAME,
            output_ref=f"{args.action.value}:{args.account_id}",
            approval_status=ApprovalStatus.APPROVED,
            detail=f"{args.action.value} applied to {args.account_id} under {approval_id}",
        )
        return {
            "account_id": account.id,
            "action": args.action.value,
            "account_status": account.status.value,
            "card_status": account.card_status.value,
        }
