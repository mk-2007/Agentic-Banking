"""Audit contracts: an append-only, tamper-evident chain of events.

Each `AuditEvent` stores the hash of the one before it and its own hash. Changing or
removing any past event breaks every later link, which `first_broken_link` detects.
This supports PRD principle 7: every decision must be reconstructable.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Final, Self

from pydantic import AwareDatetime, Field, model_validator

from .actors import Actor
from .approval import ApprovalStatus
from .base import Contract
from .evidence import PolicyRef
from .hashing import sha256_hex

GENESIS_HASH: Final[str] = "0" * 64


class AuditEventType(StrEnum):
    """Kinds of events worth recording."""

    CASE_CREATED = "case_created"
    STATE_CHANGED = "state_changed"
    TOOL_CALLED = "tool_called"
    TOOL_DENIED = "tool_denied"
    EVIDENCE_RECORDED = "evidence_recorded"
    POLICY_RETRIEVED = "policy_retrieved"
    DECISION_MADE = "decision_made"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_VOTE_CAST = "approval_vote_cast"
    ACTION_EXECUTED = "action_executed"
    ERROR = "error"


class AuditDraft(Contract):
    """The content of an audit event, before it is chained."""

    id: str = Field(min_length=1)
    timestamp: AwareDatetime
    event_type: AuditEventType
    actor: Actor
    case_id: str | None = None
    tool_name: str | None = None
    input_hash: str | None = Field(default=None, description="Hash of tool input, not the input.")
    output_ref: str | None = None
    policy_refs: tuple[PolicyRef, ...] = ()
    decision_id: str | None = None
    approval_status: ApprovalStatus | None = None
    reviewer_id: str | None = None
    detail: str = ""


class AuditEvent(AuditDraft):
    """An audit event linked into the hash chain."""

    prev_hash: str = Field(min_length=64, max_length=64)
    event_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def check_hash_matches_content(self) -> Self:
        """Check the stored hash equals the hash recomputed from the content."""
        content = self.model_dump(mode="json", exclude={"prev_hash", "event_hash"})
        if self.event_hash != _chain_hash(self.prev_hash, content):
            raise ValueError("event_hash does not match event content")
        return self


def _chain_hash(prev_hash: str, content: object) -> str:
    return sha256_hex({"prev_hash": prev_hash, "event": content})


def seal(draft: AuditDraft, prev_hash: str) -> AuditEvent:
    """Chain ``draft`` after ``prev_hash`` and return the finished event."""
    content = draft.model_dump(mode="json")
    return AuditEvent(
        **draft.model_dump(),
        prev_hash=prev_hash,
        event_hash=_chain_hash(prev_hash, content),
    )


def first_broken_link(events: Sequence[AuditEvent]) -> int | None:
    """Return the index of the first event whose link is broken, or None if intact."""
    expected_prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.prev_hash != expected_prev:
            return index
        expected_prev = event.event_hash
    return None
