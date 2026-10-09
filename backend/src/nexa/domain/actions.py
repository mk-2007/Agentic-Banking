"""The closed set of actions the platform can recommend, and how risky each one is.

The decision layer may only choose from `ActionType`. It can never invent an action
as free text, which keeps decisions checkable and keeps risk classification complete.
"""

from collections.abc import Mapping
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final


class RiskLevel(IntEnum):
    """How consequential an action is (PRD section 12)."""

    INFORMATIONAL = 1
    LOW_OPERATIONAL = 2
    SENSITIVE = 3
    HIGH_RISK = 4

    @property
    def requires_human_approval(self) -> bool:
        """Level 3 and 4 actions need a human before they can run."""
        return self >= RiskLevel.SENSITIVE


class ActionType(StrEnum):
    """Every action the decision layer may recommend."""

    NO_ACTION = "no_action"
    MONITOR_ACCOUNT = "monitor_account"
    REQUEST_KYC_DOCUMENTS = "request_kyc_documents"
    ESCALATE_TO_ANALYST = "escalate_to_analyst"
    REQUEST_CUSTOMER_VERIFICATION = "request_customer_verification"
    BLOCK_CARD = "block_card"
    FREEZE_ACCOUNT = "freeze_account"


ACTION_RISK_LEVEL: Final[Mapping[ActionType, RiskLevel]] = MappingProxyType(
    {
        ActionType.NO_ACTION: RiskLevel.INFORMATIONAL,
        ActionType.MONITOR_ACCOUNT: RiskLevel.LOW_OPERATIONAL,
        ActionType.REQUEST_KYC_DOCUMENTS: RiskLevel.LOW_OPERATIONAL,
        ActionType.ESCALATE_TO_ANALYST: RiskLevel.LOW_OPERATIONAL,
        ActionType.REQUEST_CUSTOMER_VERIFICATION: RiskLevel.SENSITIVE,
        ActionType.BLOCK_CARD: RiskLevel.SENSITIVE,
        ActionType.FREEZE_ACCOUNT: RiskLevel.HIGH_RISK,
    }
)

# When evidence is missing or contradictory, only "ask for more / hand to a human"
# actions are acceptable. Dismissing the alert or restricting the customer is not.
UNCERTAINTY_SAFE_ACTIONS: Final[frozenset[ActionType]] = frozenset(
    {
        ActionType.ESCALATE_TO_ANALYST,
        ActionType.REQUEST_KYC_DOCUMENTS,
        ActionType.REQUEST_CUSTOMER_VERIFICATION,
    }
)


def risk_level_for(action: ActionType) -> RiskLevel:
    """Return the risk level of ``action``."""
    return ACTION_RISK_LEVEL[action]
