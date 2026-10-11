"""Convenience for writing audit events: fills in id and timestamp, then appends."""

from nexa.domain.actors import Actor
from nexa.domain.approval import ApprovalStatus
from nexa.domain.audit import AuditDraft, AuditEvent, AuditEventType
from nexa.domain.clock import Clock, utc_now
from nexa.domain.evidence import PolicyRef
from nexa.domain.ids import new_id

from .log import AuditLog


class AuditRecorder:
    """Records events on an `AuditLog` using an injectable clock."""

    def __init__(self, log: AuditLog, clock: Clock = utc_now) -> None:
        self._log = log
        self._clock = clock

    def record(
        self,
        event_type: AuditEventType,
        actor: Actor,
        *,
        case_id: str | None = None,
        tool_name: str | None = None,
        input_hash: str | None = None,
        output_ref: str | None = None,
        policy_refs: tuple[PolicyRef, ...] = (),
        decision_id: str | None = None,
        approval_status: ApprovalStatus | None = None,
        reviewer_id: str | None = None,
        detail: str = "",
    ) -> AuditEvent:
        """Append one event and return it."""
        draft = AuditDraft(
            id=new_id("evt"),
            timestamp=self._clock(),
            event_type=event_type,
            actor=actor,
            case_id=case_id,
            tool_name=tool_name,
            input_hash=input_hash,
            output_ref=output_ref,
            policy_refs=policy_refs,
            decision_id=decision_id,
            approval_status=approval_status,
            reviewer_id=reviewer_id,
            detail=detail,
        )
        return self._log.append(draft)
