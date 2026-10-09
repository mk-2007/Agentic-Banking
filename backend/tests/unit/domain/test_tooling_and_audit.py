import pytest
from builders import NOW, human, minutes
from pydantic import ValidationError

from nexa.domain.actions import RiskLevel
from nexa.domain.actors import Role
from nexa.domain.approval import ApprovalStatus
from nexa.domain.audit import (
    GENESIS_HASH,
    AuditDraft,
    AuditEvent,
    AuditEventType,
    first_broken_link,
    seal,
)
from nexa.domain.tooling import ToolResult, ToolSpec


def test_tool_spec_rules() -> None:
    ToolSpec(
        name="get_transaction",
        description="Read one transaction.",
        risk_level=RiskLevel.INFORMATIONAL,
        required_roles=(Role.DATA_AGENT,),
        read_only=True,
    )
    with pytest.raises(ValidationError, match="snake_case"):
        ToolSpec(
            name="GetTransaction",
            description="x",
            risk_level=RiskLevel.INFORMATIONAL,
            required_roles=(Role.DATA_AGENT,),
            read_only=True,
        )
    with pytest.raises(ValidationError, match="at least Level 2"):
        ToolSpec(
            name="update_customer",
            description="x",
            risk_level=RiskLevel.INFORMATIONAL,
            required_roles=(Role.DATA_AGENT,),
            read_only=False,
        )
    with pytest.raises(ValidationError):  # a tool nobody may call is a bug
        ToolSpec(
            name="orphan",
            description="x",
            risk_level=RiskLevel.INFORMATIONAL,
            required_roles=(),
            read_only=True,
        )


def test_tool_result_is_either_success_or_error() -> None:
    ToolResult(call_id="c1", ok=True, output={"amount": 120.5})
    ToolResult(call_id="c1", ok=False, error_code="permission_denied")
    with pytest.raises(ValidationError):
        ToolResult(call_id="c1", ok=True, error_code="oops")
    with pytest.raises(ValidationError):
        ToolResult(call_id="c1", ok=False)


def draft(n: int, kind: AuditEventType = AuditEventType.STATE_CHANGED) -> AuditDraft:
    return AuditDraft(
        id=f"evt_{n}",
        timestamp=minutes(n),
        event_type=kind,
        actor=human(),
        case_id="case_1",
        approval_status=ApprovalStatus.PENDING if n == 2 else None,
        detail=f"step {n}",
    )


def build_chain(length: int = 4) -> list[AuditEvent]:
    chain: list[AuditEvent] = []
    prev = GENESIS_HASH
    for n in range(length):
        event = seal(draft(n), prev)
        chain.append(event)
        prev = event.event_hash
    return chain


def test_intact_chain_has_no_broken_link() -> None:
    assert first_broken_link(build_chain()) is None
    assert first_broken_link([]) is None


def test_sealing_is_deterministic() -> None:
    assert seal(draft(1), GENESIS_HASH) == seal(draft(1), GENESIS_HASH)


def test_editing_an_event_is_detected_at_construction() -> None:
    event = build_chain()[1]
    tampered = {**event.model_dump(), "detail": "something else"}
    with pytest.raises(ValidationError, match="event_hash"):
        AuditEvent(**tampered)


def test_removing_an_event_breaks_the_chain() -> None:
    chain = build_chain()
    del chain[1]
    assert first_broken_link(chain) == 1


def test_reordering_events_breaks_the_chain() -> None:
    chain = build_chain()
    chain[1], chain[2] = chain[2], chain[1]
    assert first_broken_link(chain) == 1


def test_chain_must_start_at_genesis() -> None:
    chain = build_chain()
    assert first_broken_link(chain[1:]) == 0


def test_audit_events_are_immutable() -> None:
    event = build_chain(1)[0]
    with pytest.raises(ValidationError):
        event.detail = "changed"  # type: ignore[misc]
    assert event.timestamp == NOW
