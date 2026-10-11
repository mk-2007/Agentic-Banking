"""Which roles may call which tools: the permission matrix, as configuration.

This is the single source of truth for tool access. A tool that is not listed here cannot be
registered, and a role that is not listed for a tool is denied (deny by default). Changing who
may do what is a configuration change plus a test update, never a prompt change.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from nexa.domain.actors import Role

_HUMAN_INVESTIGATORS = (Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER)

TOOL_ROLES: Final[Mapping[str, frozenset[Role]]] = MappingProxyType(
    {
        "get_customer_profile": frozenset({Role.DATA_AGENT, *_HUMAN_INVESTIGATORS}),
        "get_account_details": frozenset({Role.DATA_AGENT, *_HUMAN_INVESTIGATORS}),
        "get_transaction_details": frozenset(
            {Role.DATA_AGENT, Role.ANALYSIS_AGENT, *_HUMAN_INVESTIGATORS}
        ),
        "get_transaction_history": frozenset(
            {Role.DATA_AGENT, Role.ANALYSIS_AGENT, *_HUMAN_INVESTIGATORS}
        ),
        "get_kyc_status": frozenset({Role.DATA_AGENT, *_HUMAN_INVESTIGATORS}),
        "search_knowledge_base": frozenset(
            {
                Role.CUSTOMER_SERVICE_AGENT,
                Role.POLICY_AGENT,
                Role.VERIFICATION_AGENT,
                *_HUMAN_INVESTIGATORS,
            }
        ),
        # Only the execution service may change bank state, and only with an approval.
        "execute_authorized_action": frozenset({Role.EXECUTION_SERVICE}),
    }
)


def roles_for(tool_name: str) -> tuple[Role, ...]:
    """Return the roles allowed to call ``tool_name`` (sorted for stable output)."""
    return tuple(sorted(TOOL_ROLES[tool_name], key=lambda r: r.value))
