"""Roles, permissions and the deterministic policy engine.

Why: Authorization is plain code, never an LLM. It decides what an actor may do (PRD principle 3,
section 21).

Where it sits: Layer 1. Used by tools and approvals.

Modules:
    decisions       allow/deny result, stable denial reasons, `AuthorizationDenied`
    permissions     role check against the permission matrix (deny by default)
    scope           agents may only touch the customer and accounts of their case
    approval_gate   an approval authorizes one action, one account, one case, once
"""

from .approval_gate import ApprovalSource, verify_execution_approval
from .decisions import AuthorizationDecision, AuthorizationDenied, DenialReason
from .permissions import authorize_role
from .scope import CaseScope, CaseScopeProvider, check_scope

__all__ = [
    "ApprovalSource",
    "AuthorizationDecision",
    "AuthorizationDenied",
    "CaseScope",
    "CaseScopeProvider",
    "DenialReason",
    "authorize_role",
    "check_scope",
    "verify_execution_approval",
]
