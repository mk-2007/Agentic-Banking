"""Who must approve each consequential action, and for how long an approval stays valid.

The matrix is configuration so a bank can change it without touching code. The rules that
make a matrix *safe* (Level 4 needs two different roles, only bank approvers may approve)
are checked every time an `ApprovalRule` is built.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Self

from pydantic import Field, model_validator

from nexa.domain.actions import ActionType, RiskLevel, risk_level_for
from nexa.domain.actors import APPROVER_ROLES, Role
from nexa.domain.base import Contract


class ApprovalRule(Contract):
    """Approval requirements for one action."""

    action: ActionType
    required_roles: tuple[Role, ...] = Field(min_length=1)
    expiry_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def check_rule_is_safe(self) -> Self:
        """Check the rule only covers Level 3+ actions and respects the safety rules."""
        level = risk_level_for(self.action)
        if not level.requires_human_approval:
            raise ValueError(f"{self.action.value} is Level {level.value}; it needs no approval")
        if len(set(self.required_roles)) != len(self.required_roles):
            raise ValueError("required_roles must be unique")
        if not set(self.required_roles) <= APPROVER_ROLES:
            raise ValueError("required_roles must be bank approver roles")
        if level is RiskLevel.HIGH_RISK and len(self.required_roles) < 2:
            raise ValueError("Level 4 actions need at least two different approver roles")
        return self


APPROVAL_MATRIX: Final[Mapping[ActionType, ApprovalRule]] = MappingProxyType(
    {
        rule.action: rule
        for rule in (
            ApprovalRule(
                action=ActionType.REQUEST_CUSTOMER_VERIFICATION,
                required_roles=(Role.FRAUD_ANALYST,),
                expiry_minutes=240,
            ),
            ApprovalRule(
                action=ActionType.BLOCK_CARD,
                required_roles=(Role.FRAUD_ANALYST,),
                expiry_minutes=60,
            ),
            ApprovalRule(
                action=ActionType.FREEZE_ACCOUNT,
                required_roles=(Role.FRAUD_ANALYST, Role.RISK_OFFICER),
                expiry_minutes=120,
            ),
        )
    }
)


def approval_rule_for(action: ActionType) -> ApprovalRule | None:
    """Return the approval rule for ``action``, or None if it needs no human approval."""
    return APPROVAL_MATRIX.get(action)
