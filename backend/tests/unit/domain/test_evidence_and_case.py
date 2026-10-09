from datetime import datetime

import pytest
from builders import NOW, POLICY, make_case, minutes
from pydantic import ValidationError

from nexa.domain.case import ALLOWED_TRANSITIONS, CaseStatus
from nexa.domain.errors import InvalidTransitionError
from nexa.domain.evidence import Evidence, EvidenceKind, SourceRef


def test_source_needs_provenance() -> None:
    SourceRef(tool_name="get_transaction", record_id="txn_1")
    SourceRef(policy=POLICY)
    with pytest.raises(ValidationError):
        SourceRef()
    with pytest.raises(ValidationError):
        SourceRef(tool_name="get_transaction")  # record id missing


def test_evidence_rejects_naive_timestamps_and_unknown_fields() -> None:
    source = SourceRef(tool_name="get_transaction", record_id="txn_1")
    fields = {
        "id": "ev_1",
        "case_id": "case_1",
        "kind": EvidenceKind.TRANSACTION,
        "summary": "Amount 9x customer average",
        "source": source,
    }
    Evidence(**fields, collected_at=NOW)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Evidence(**fields, collected_at=datetime(2026, 1, 1))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Evidence(**fields, collected_at=NOW, surprise="x")  # type: ignore[arg-type]


def test_every_status_has_transition_rules() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(CaseStatus)


def test_happy_path_through_to_completion() -> None:
    path = [
        CaseStatus.PLANNING,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.DECISION_READY,
        CaseStatus.WAITING_FOR_APPROVAL,
        CaseStatus.APPROVED,
        CaseStatus.EXECUTED,
        CaseStatus.VERIFIED,
        CaseStatus.COMPLETED,
    ]
    case = make_case()
    for step, status in enumerate(path, start=1):
        case = case.transition_to(status, minutes(step))
    assert case.status is CaseStatus.COMPLETED
    assert case.is_terminal
    assert case.updated_at == minutes(len(path))


def test_cannot_skip_verification_or_approval() -> None:
    case = make_case().transition_to(CaseStatus.PLANNING, minutes(1))
    with pytest.raises(InvalidTransitionError):
        case.transition_to(CaseStatus.EXECUTED, minutes(2))
    with pytest.raises(InvalidTransitionError):
        make_case(status=CaseStatus.DECISION_READY).transition_to(CaseStatus.EXECUTED, minutes(2))


@pytest.mark.parametrize(
    "terminal",
    [s for s, nxt in ALLOWED_TRANSITIONS.items() if not nxt],
)
def test_terminal_states_are_final(terminal: CaseStatus) -> None:
    case = make_case(status=terminal)
    assert case.is_terminal
    for target in CaseStatus:
        assert not case.can_transition_to(target)


def test_transition_does_not_mutate_the_original() -> None:
    original = make_case()
    moved = original.transition_to(CaseStatus.PLANNING, minutes(1))
    assert original.status is CaseStatus.CREATED
    assert moved.status is CaseStatus.PLANNING


def test_updated_at_cannot_precede_created_at() -> None:
    with pytest.raises(ValidationError):
        make_case(updated_at=minutes(-5))
