"""Role-based tool permissions: deny by default."""

from collections.abc import Collection

from nexa.domain.actors import Actor, Role

from .decisions import AuthorizationDecision, DenialReason


def authorize_role(actor: Actor, allowed_roles: Collection[Role]) -> AuthorizationDecision:
    """Allow only if the actor holds one of ``allowed_roles``.

    An actor with no role (for example a roleless system actor) is always denied, and so is
    any role not explicitly listed. Nothing is permitted by omission.
    """
    if actor.role is None:
        return AuthorizationDecision.deny(DenialReason.NO_ROLE, f"{actor.kind.value} has no role")
    if actor.role not in allowed_roles:
        return AuthorizationDecision.deny(
            DenialReason.ROLE_NOT_PERMITTED, f"role {actor.role.value} may not do this"
        )
    return AuthorizationDecision.allow()
