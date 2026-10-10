import pytest
from pydantic import ValidationError

from nexa.config import APPROVAL_MATRIX, DEFAULT_THRESHOLDS, ApprovalRule, approval_rule_for
from nexa.domain.actions import ActionType, risk_level_for
from nexa.domain.actors import Role


def test_matrix_covers_exactly_the_actions_that_need_approval() -> None:
    needing_approval = {a for a in ActionType if risk_level_for(a).requires_human_approval}
    assert set(APPROVAL_MATRIX) == needing_approval


def test_low_risk_actions_have_no_rule() -> None:
    assert approval_rule_for(ActionType.NO_ACTION) is None
    assert approval_rule_for(ActionType.ESCALATE_TO_ANALYST) is None


def test_freezing_needs_two_different_roles() -> None:
    rule = approval_rule_for(ActionType.FREEZE_ACCOUNT)
    assert rule is not None
    assert set(rule.required_roles) == {Role.FRAUD_ANALYST, Role.RISK_OFFICER}


def test_rule_rejects_unsafe_configurations() -> None:
    analyst = (Role.FRAUD_ANALYST,)
    with pytest.raises(ValidationError, match="two different"):
        ApprovalRule(action=ActionType.FREEZE_ACCOUNT, required_roles=analyst, expiry_minutes=5)
    with pytest.raises(ValidationError, match="needs no approval"):
        ApprovalRule(action=ActionType.NO_ACTION, required_roles=analyst, expiry_minutes=5)
    with pytest.raises(ValidationError, match="approver roles"):
        ApprovalRule(
            action=ActionType.BLOCK_CARD, required_roles=(Role.DECISION_AGENT,), expiry_minutes=5
        )
    with pytest.raises(ValidationError):
        ApprovalRule(action=ActionType.BLOCK_CARD, required_roles=analyst, expiry_minutes=0)


def test_default_thresholds_are_sensible_and_immutable() -> None:
    assert DEFAULT_THRESHOLDS.amount_multiple_of_average > 1
    with pytest.raises(ValidationError):
        DEFAULT_THRESHOLDS.failed_auth_attempts = 99  # type: ignore[misc]
