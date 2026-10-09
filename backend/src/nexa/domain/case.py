"""The investigation case and its state machine (PRD sections 37-39).

A `Case` is immutable. Moving it forward returns a new copy, and only transitions listed in
`ALLOWED_TRANSITIONS` are legal. Failure states are real states, not exceptions, so every
way a case can end is visible, auditable and testable.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Self

from pydantic import AwareDatetime, Field, model_validator

from .base import Contract
from .errors import InvalidTransitionError


class CaseStatus(StrEnum):
    """Lifecycle states of a case."""

    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_FOR_TOOL = "waiting_for_tool"
    VERIFYING = "verifying"
    DECISION_READY = "decision_ready"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    APPROVED = "approved"
    EXECUTED = "executed"
    VERIFIED = "verified"
    COMPLETED = "completed"
    # Ways a case can end without completing normally
    FAILED_TOOL = "failed_tool"
    FAILED_VALIDATION = "failed_validation"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    REJECTED_BY_HUMAN = "rejected_by_human"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"


S = CaseStatus

ALLOWED_TRANSITIONS: Final[Mapping[CaseStatus, frozenset[CaseStatus]]] = MappingProxyType(
    {
        S.CREATED: frozenset({S.PLANNING}),
        S.PLANNING: frozenset({S.EXECUTING, S.ESCALATED}),
        S.EXECUTING: frozenset({S.WAITING_FOR_TOOL, S.VERIFYING, S.TIMED_OUT}),
        S.WAITING_FOR_TOOL: frozenset({S.EXECUTING, S.FAILED_TOOL, S.TIMED_OUT}),
        # From VERIFYING a case may loop back to gather more evidence (bounded by loop limits).
        S.VERIFYING: frozenset({S.DECISION_READY, S.EXECUTING, S.FAILED_VALIDATION, S.ESCALATED}),
        S.DECISION_READY: frozenset(
            {S.WAITING_FOR_APPROVAL, S.APPROVED, S.BLOCKED_BY_POLICY, S.ESCALATED}
        ),
        S.WAITING_FOR_APPROVAL: frozenset(
            {S.APPROVED, S.REJECTED_BY_HUMAN, S.DECISION_READY, S.ESCALATED, S.TIMED_OUT}
        ),
        S.APPROVED: frozenset({S.EXECUTED, S.FAILED_TOOL, S.BLOCKED_BY_POLICY}),
        S.EXECUTED: frozenset({S.VERIFIED, S.FAILED_VALIDATION}),
        S.VERIFIED: frozenset({S.COMPLETED}),
        # Terminal states: nothing may follow them.
        S.COMPLETED: frozenset(),
        S.FAILED_TOOL: frozenset(),
        S.FAILED_VALIDATION: frozenset(),
        S.BLOCKED_BY_POLICY: frozenset(),
        S.REJECTED_BY_HUMAN: frozenset(),
        S.ESCALATED: frozenset(),
        S.TIMED_OUT: frozenset(),
    }
)


class Alert(Contract):
    """The trigger that opens a case, for example a flagged transaction."""

    id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    trigger: str = Field(min_length=1, description="Name of the rule or signal that fired.")
    raised_at: AwareDatetime


class Case(Contract):
    """One investigation, from alert to completion."""

    id: str = Field(min_length=1)
    alert: Alert
    status: CaseStatus = CaseStatus.CREATED
    created_at: AwareDatetime
    updated_at: AwareDatetime
    evidence_ids: tuple[str, ...] = ()
    decision_id: str | None = None

    @model_validator(mode="after")
    def check_timestamps(self) -> Self:
        """Reject a case that was updated before it was created."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self

    @property
    def is_terminal(self) -> bool:
        """True once no further transition is possible."""
        return not ALLOWED_TRANSITIONS[self.status]

    def can_transition_to(self, new_status: CaseStatus) -> bool:
        """Return whether moving to ``new_status`` is legal from the current status."""
        return new_status in ALLOWED_TRANSITIONS[self.status]

    def transition_to(self, new_status: CaseStatus, at: AwareDatetime) -> Self:
        """Return a copy of this case moved to ``new_status``.

        Raises:
            InvalidTransitionError: if the move is not allowed.

        """
        if not self.can_transition_to(new_status):
            raise InvalidTransitionError(
                f"cannot move case {self.id} from {self.status.value} to {new_status.value}"
            )
        return self.model_copy(update={"status": new_status, "updated_at": at})
