"""Who may retrieve which knowledge, as configuration.

Two independent limits apply and the stricter one wins:

- the **role** limit: the highest sensitivity a role may ever read;
- the **channel** limit: a customer-facing session can never read above PUBLIC, whichever agent
  is serving it. The channel is set by trusted code, so a confused or manipulated agent cannot
  talk its way into internal material.

A role with no entry has no clearance at all (deny by default).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from nexa.domain.actors import Role, SessionChannel
from nexa.domain.knowledge import Sensitivity

ROLE_CLEARANCE: Final[Mapping[Role, Sensitivity]] = MappingProxyType(
    {
        Role.CUSTOMER: Sensitivity.PUBLIC,
        Role.CUSTOMER_SERVICE_AGENT: Sensitivity.PUBLIC,
        Role.SUPERVISOR_AGENT: Sensitivity.INTERNAL,
        Role.REPORTING_AGENT: Sensitivity.INTERNAL,
        Role.ANALYSIS_AGENT: Sensitivity.INTERNAL,
        Role.POLICY_AGENT: Sensitivity.RESTRICTED,
        Role.VERIFICATION_AGENT: Sensitivity.RESTRICTED,
        Role.FRAUD_ANALYST: Sensitivity.RESTRICTED,
        Role.RISK_OFFICER: Sensitivity.RESTRICTED,
        Role.COMPLIANCE_OFFICER: Sensitivity.RESTRICTED,
    }
)

CHANNEL_CAP: Final[Mapping[SessionChannel, Sensitivity]] = MappingProxyType(
    {
        SessionChannel.CUSTOMER: Sensitivity.PUBLIC,
        SessionChannel.EMPLOYEE: Sensitivity.RESTRICTED,
    }
)


def effective_clearance(role: Role | None, channel: SessionChannel) -> Sensitivity | None:
    """Return the highest sensitivity readable by ``role`` on ``channel``, or None for no access."""
    if role is None or role not in ROLE_CLEARANCE:
        return None
    return min(ROLE_CLEARANCE[role], CHANNEL_CAP[channel])
