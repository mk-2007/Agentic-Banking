"""Who is calling: a bearer token maps to a user id and a role, and the role decides the channel.

The session channel is trusted input. It is derived here, in code, from the authenticated role
and is never read from a request body: a customer principal can only ever get the customer
channel, so a customer cannot reach internal or restricted knowledge however the request is
phrased.

Tokens come from the environment (``NEXA_API_TOKENS``) or are generated at start-up for a demo;
none is written in code. Authentication here is deliberately simple (static bearer tokens held in
memory); a real deployment would put an identity provider in front.
"""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass

from nexa.domain.actors import Role, SessionChannel

EMPLOYEE_ROLES = frozenset({Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER})
ALLOWED_ROLES = EMPLOYEE_ROLES | {Role.CUSTOMER}


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    user_id: str
    role: Role

    @property
    def is_employee(self) -> bool:
        """True for the human investigator roles."""
        return self.role in EMPLOYEE_ROLES

    @property
    def channel(self) -> SessionChannel:
        """The session channel for this caller: employee only for staff, customer otherwise."""
        return SessionChannel.EMPLOYEE if self.is_employee else SessionChannel.CUSTOMER


def parse_tokens(spec: str) -> dict[str, Principal]:
    """Parse ``token:user_id:role`` entries separated by commas.

    Raises ``ValueError`` for a malformed entry, an unknown or non-human role, or a repeated token.
    """
    found: dict[str, Principal] = {}
    for entry in filter(None, (part.strip() for part in spec.split(","))):
        pieces = entry.split(":")
        if len(pieces) != 3 or not all(pieces):
            raise ValueError("each token entry must look like token:user_id:role")
        token, user_id, role_name = pieces
        try:
            role = Role(role_name)
        except ValueError:
            raise ValueError(f"unknown role {role_name!r}") from None
        if role not in ALLOWED_ROLES:
            raise ValueError(f"role {role_name!r} cannot sign in to the API")
        if token in found:
            raise ValueError("a token may be used only once")
        found[token] = Principal(user_id, role)
    return found


def demo_tokens() -> dict[str, Principal]:
    """Create random tokens for a demo analyst, risk officer and customer (new on every start)."""
    people = (
        ("demo_analyst", Role.FRAUD_ANALYST),
        ("demo_risk_officer", Role.RISK_OFFICER),
        ("demo_customer", Role.CUSTOMER),
    )
    return {secrets.token_urlsafe(24): Principal(user, role) for user, role in people}


def describe(tokens: Mapping[str, Principal]) -> str:
    """List who can sign in (user and role, never the token) for logs."""
    return ", ".join(f"{p.user_id} ({p.role.value})" for p in tokens.values())
