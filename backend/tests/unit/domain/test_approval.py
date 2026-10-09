import pytest
from builders import NOW, make_request, minutes, vote
from pydantic import ValidationError

from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Role
from nexa.domain.approval import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalVote,
    Verdict,
    evaluate_approval,
)

FA, RO, CO = Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER


def status(votes: list[ApprovalVote], at: int = 10) -> ApprovalStatus:
    return evaluate_approval(make_request(), votes, minutes(at))


def test_no_votes_is_pending() -> None:
    assert status([]) == ApprovalStatus.PENDING


def test_level_four_needs_every_required_role() -> None:
    assert status([vote("ana", FA, Verdict.APPROVE)]) == ApprovalStatus.PENDING
    both = [vote("ana", FA, Verdict.APPROVE), vote("raj", RO, Verdict.APPROVE)]
    assert status(both) == ApprovalStatus.APPROVED


def test_one_person_cannot_fill_two_roles() -> None:
    votes = [vote("ana", FA, Verdict.APPROVE), vote("ana", RO, Verdict.APPROVE, at_minute=6)]
    # Latest vote wins for a person, so "ana" now only counts as risk officer.
    assert status(votes) == ApprovalStatus.PENDING


def test_any_rejection_wins_over_approvals() -> None:
    votes = [
        vote("ana", FA, Verdict.APPROVE),
        vote("raj", RO, Verdict.APPROVE),
        vote("cat", CO, Verdict.REJECT),
    ]
    assert status(votes) == ApprovalStatus.REJECTED


def test_escalate_and_modify_are_surfaced() -> None:
    assert status([vote("ana", FA, Verdict.ESCALATE)]) == ApprovalStatus.ESCALATED
    assert status([vote("ana", FA, Verdict.MODIFY)]) == ApprovalStatus.MODIFICATION_REQUESTED


def test_a_reviewer_can_change_their_mind() -> None:
    votes = [vote("ana", FA, Verdict.REJECT, 5), vote("ana", FA, Verdict.APPROVE, 6)]
    votes.append(vote("raj", RO, Verdict.APPROVE, 7))
    assert status(votes) == ApprovalStatus.APPROVED


def test_expired_request_is_never_approved() -> None:
    both = [vote("ana", FA, Verdict.APPROVE), vote("raj", RO, Verdict.APPROVE)]
    assert status(both, at=61) == ApprovalStatus.EXPIRED
    assert status([], at=61) == ApprovalStatus.EXPIRED


def test_late_and_foreign_votes_are_ignored() -> None:
    late = vote("ana", FA, Verdict.APPROVE, at_minute=70)
    other_request = ApprovalVote(
        request_id="apr_other",
        approver_id="raj",
        role=RO,
        verdict=Verdict.APPROVE,
        decided_at=minutes(5),
    )
    customer = vote("cust", Role.CUSTOMER, Verdict.APPROVE)
    assert status([late, other_request, customer], at=30) == ApprovalStatus.PENDING


def test_level_four_request_needs_two_distinct_approver_roles() -> None:
    with pytest.raises(ValidationError, match="two different"):
        make_request(roles=(FA,))
    with pytest.raises(ValidationError, match="unique"):
        make_request(roles=(FA, FA))


def test_request_roles_must_be_bank_approvers() -> None:
    with pytest.raises(ValidationError, match="approver roles"):
        make_request(roles=(FA, Role.CUSTOMER))


def test_low_risk_actions_do_not_get_approval_requests() -> None:
    with pytest.raises(ValidationError, match="Level 3 and Level 4"):
        make_request(ActionType.NO_ACTION)


def test_level_three_needs_one_approver() -> None:
    req = make_request(ActionType.BLOCK_CARD, roles=(FA,))
    assert risk_level_for(req.action).requires_human_approval
    approve = vote("ana", FA, Verdict.APPROVE)
    assert evaluate_approval(req, [approve], minutes(10)) == ApprovalStatus.APPROVED


def test_request_must_expire_after_it_is_made() -> None:
    good = make_request()
    with pytest.raises(ValidationError, match="expires_at"):
        ApprovalRequest(**{**good.model_dump(), "expires_at": NOW})
