"""Who can do things: roles and actors (humans, agents, the system itself)."""

from enum import StrEnum
from typing import Final, Self

from pydantic import model_validator

from .base import Contract


class Role(StrEnum):
    """Every role known to the permission model."""

    # Humans
    CUSTOMER = "customer"
    FRAUD_ANALYST = "fraud_analyst"
    RISK_OFFICER = "risk_officer"
    COMPLIANCE_OFFICER = "compliance_officer"
    # Agents
    SUPERVISOR_AGENT = "supervisor_agent"
    DATA_AGENT = "data_agent"
    POLICY_AGENT = "policy_agent"
    ANALYSIS_AGENT = "analysis_agent"
    VERIFICATION_AGENT = "verification_agent"
    DECISION_AGENT = "decision_agent"
    RISK_AGENT = "risk_agent"
    REPORTING_AGENT = "reporting_agent"

    @property
    def is_human(self) -> bool:
        """True for roles held by people."""
        return self in HUMAN_ROLES


HUMAN_ROLES: Final[frozenset[Role]] = frozenset(
    {Role.CUSTOMER, Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER}
)
# Humans who work at the bank and may approve actions (customers never approve).
APPROVER_ROLES: Final[frozenset[Role]] = frozenset(
    {Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER}
)


class ActorKind(StrEnum):
    """What kind of thing is acting."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class Actor(Contract):
    """Whoever performs an action; recorded on every tool call and audit event."""

    kind: ActorKind
    id: str
    role: Role | None = None

    @model_validator(mode="after")
    def check_role_matches_kind(self) -> Self:
        """Users hold human roles, agents hold agent roles, the system has no role."""
        if self.kind is ActorKind.SYSTEM:
            if self.role is not None:
                raise ValueError("system actors must not have a role")
        elif self.role is None:
            raise ValueError(f"{self.kind.value} actors need a role")
        elif (self.kind is ActorKind.USER) != self.role.is_human:
            raise ValueError(f"role {self.role.value} does not fit actor kind {self.kind.value}")
        return self
