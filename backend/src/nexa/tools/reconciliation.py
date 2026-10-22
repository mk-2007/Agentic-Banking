"""Reconciliation of the bank's state against what the audit log says was done.

Two kinds of difference are reported, each as a `Mismatch` an operations team can pick up:
an action the log says was applied that the bank does not show (`not_applied`), and an approved
action whose execution failed for good after retries (`execution_failed`).

shortcut: reads the audit log and the simulator in one pass; against a real core banking system this
becomes a scheduled job over the bank's own statement feed.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from nexa.bank_sim.gateway import BankGateway
from nexa.bank_sim.models import AccountStatus, CardStatus
from nexa.domain.actions import ActionType
from nexa.domain.audit import AuditEvent, AuditEventType

from .execution import FAILED_PREFIX


@dataclass(frozen=True)
class Mismatch:
    """One difference that needs a human."""

    kind: str  # "not_applied" or "execution_failed"
    case_id: str | None
    account_id: str
    action: str


def reconcile(events: Iterable[AuditEvent], bank: BankGateway) -> list[Mismatch]:
    """Compare executed and failed actions in the audit log with the bank's current state."""
    found: list[Mismatch] = []
    for event in events:
        ref = (event.output_ref or "").split(":")
        if event.event_type is AuditEventType.ACTION_EXECUTED and len(ref) == 2:
            action, account_id = ref
            account = bank.get_account(account_id)
            applied = (
                account.status is AccountStatus.FROZEN
                if action == ActionType.FREEZE_ACCOUNT.value
                else account.card_status is CardStatus.BLOCKED
            )
            if not applied:
                found.append(Mismatch("not_applied", event.case_id, account_id, action))
        elif event.event_type is AuditEventType.ERROR and ref[0] == FAILED_PREFIX and len(ref) == 4:
            found.append(Mismatch("execution_failed", event.case_id, ref[2], ref[1]))
    return found
