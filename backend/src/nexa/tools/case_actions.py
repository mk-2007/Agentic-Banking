"""The tool that carries out a case's follow-up actions: watch, ask, escalate, or close.

Blocking a card or freezing an account stay with `execute_authorized_action`. This tool covers the
rest of the closed action set. Levels 1 and 2 need no approval because nothing a customer holds is
restricted: they only queue a follow-up on the bank's operations desk. Level 3
`request_customer_verification` contacts the customer, so it needs the same single-use approval as
any other sensitive action. Only the execution service may call it.
"""

from types import MappingProxyType
from typing import ClassVar, Final

from pydantic import Field

from nexa.bank_sim.models import OutboxKind
from nexa.config import roles_for
from nexa.domain.actions import ACTION_RISK_LEVEL, ActionType, RiskLevel
from nexa.domain.approval import ApprovalStatus
from nexa.domain.audit import AuditEventType
from nexa.domain.base import Contract, JsonDict
from nexa.domain.tooling import ToolCall, ToolSpec
from nexa.security import AuthorizationDecision, DenialReason

from .base import Tool, ToolContext
from .execution import consume_approval

NAME = "perform_case_action"

# What each action asks the operations desk to do. no_action queues nothing; it only closes.
FOLLOWUPS: Final = MappingProxyType(
    {
        ActionType.MONITOR_ACCOUNT: OutboxKind.WATCH,
        ActionType.REQUEST_KYC_DOCUMENTS: OutboxKind.KYC_REQUEST,
        ActionType.REQUEST_CUSTOMER_VERIFICATION: OutboxKind.VERIFICATION_REQUEST,
        ActionType.ESCALATE_TO_ANALYST: OutboxKind.ANALYST_TICKET,
    }
)
PERFORMABLE_ACTIONS = frozenset({ActionType.NO_ACTION, *FOLLOWUPS})


class _PerformArgs(Contract):
    account_id: str = Field(min_length=1)
    action: ActionType


class PerformCaseAction(Tool):
    """Queue the follow-up a case recommended; sensitive ones need a valid approval."""

    spec: ClassVar[ToolSpec] = ToolSpec(
        name=NAME,
        description="Carry out a non-restricting case action. Level 3 needs a valid approval id.",
        risk_level=RiskLevel.SENSITIVE,
        required_roles=roles_for(NAME),
        read_only=False,
    )

    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Check the approval where the action needs one, then queue the follow-up."""
        args = _PerformArgs.model_validate(call.arguments)
        if args.action not in PERFORMABLE_ACTIONS:
            AuthorizationDecision.deny(
                DenialReason.UNSUPPORTED_ACTION, f"{args.action.value} is not performed here"
            ).raise_if_denied()

        approval_id: str | None = None
        if ACTION_RISK_LEVEL[args.action].requires_human_approval:
            approval_id = consume_approval(call, ctx, args.action, args.account_id)

        entry_id: str | None = None
        kind = FOLLOWUPS.get(args.action)
        if kind is not None:
            entry_id = ctx.bank.queue_followup(
                args.account_id, kind, call.case_id or "", ctx.clock()
            ).id

        ctx.audit.record(
            AuditEventType.ACTION_EXECUTED,
            call.actor,
            case_id=call.case_id,
            tool_name=NAME,
            approval_status=ApprovalStatus.APPROVED if approval_id else None,
            detail=f"{args.action.value} for {args.account_id}"
            + (f" under {approval_id}" if approval_id else " (no approval needed)"),
        )
        return {
            "account_id": args.account_id,
            "action": args.action.value,
            "recorded": args.action.value,
            "followup_id": entry_id,
        }
