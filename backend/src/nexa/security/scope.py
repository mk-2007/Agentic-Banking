"""Case scoping: an agent working on one case may only see that case's customer and accounts.

This is least privilege (KB section 11.2) enforced in code. Even a role that may call
``get_account_details`` cannot use it to browse accounts unrelated to the case at hand.
Human investigators are governed by role and audit instead; scoping applies to agents.
"""

from typing import Protocol

from pydantic import Field

from nexa.domain.actors import Actor, ActorKind
from nexa.domain.base import Contract

from .decisions import AuthorizationDecision, DenialReason


class CaseScope(Contract):
    """The records a case is allowed to touch."""

    case_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    account_ids: tuple[str, ...] = Field(min_length=1)


class CaseScopeProvider(Protocol):
    """Source of truth for what each case may access (implemented by case management)."""

    def get_scope(self, case_id: str) -> CaseScope | None:
        """Return the scope of ``case_id``, or None if the case is unknown."""
        ...


def check_scope(
    provider: CaseScopeProvider,
    actor: Actor,
    case_id: str | None,
    *,
    customer_id: str | None = None,
    account_id: str | None = None,
) -> AuthorizationDecision:
    """Allow access to ``customer_id`` / ``account_id`` only inside the case's scope.

    Non-agent actors are not scope-limited here. Agents must name a known case, and every
    target they ask for must belong to it.
    """
    if actor.kind is not ActorKind.AGENT:
        return AuthorizationDecision.allow()
    if case_id is None:
        return AuthorizationDecision.deny(DenialReason.CASE_REQUIRED, "agents must name a case")
    scope = provider.get_scope(case_id)
    if scope is None:
        return AuthorizationDecision.deny(DenialReason.OUT_OF_SCOPE, "unknown case")
    if customer_id is not None and customer_id != scope.customer_id:
        return AuthorizationDecision.deny(
            DenialReason.OUT_OF_SCOPE, "customer is not part of this case"
        )
    if account_id is not None and account_id not in scope.account_ids:
        return AuthorizationDecision.deny(
            DenialReason.OUT_OF_SCOPE, "account is not part of this case"
        )
    return AuthorizationDecision.allow()
