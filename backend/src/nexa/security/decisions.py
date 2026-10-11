"""The result of an authorization check, and the exception that carries a denial."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from nexa.domain.base import Contract
from nexa.domain.errors import DomainError


class DenialReason(StrEnum):
    """Stable machine-readable reasons an action can be denied."""

    UNKNOWN_TOOL = "unknown_tool"
    NO_ROLE = "no_role"
    ROLE_NOT_PERMITTED = "role_not_permitted"
    CASE_REQUIRED = "case_required"
    OUT_OF_SCOPE = "out_of_scope"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_NOT_FOUND = "approval_not_found"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_NOT_APPROVED = "approval_not_approved"
    APPROVAL_ALREADY_USED = "approval_already_used"
    UNSUPPORTED_ACTION = "unsupported_action"


class AuthorizationDecision(Contract):
    """Allow, or deny with a reason. There is no third state."""

    allowed: bool
    reason: DenialReason | None = None
    detail: str = ""

    @model_validator(mode="after")
    def check_reason_matches_outcome(self) -> Self:
        """Require a reason exactly when the decision is a denial."""
        if self.allowed == (self.reason is not None):
            raise ValueError("a denial needs a reason, and an allow must not have one")
        return self

    @classmethod
    def allow(cls) -> Self:
        """Build an allow decision."""
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: DenialReason, detail: str = "") -> Self:
        """Build a deny decision."""
        return cls(allowed=False, reason=reason, detail=detail)

    def raise_if_denied(self) -> None:
        """Raise `AuthorizationDenied` when this decision is a denial."""
        if not self.allowed and self.reason is not None:
            raise AuthorizationDenied(self.reason, self.detail)


class AuthorizationDenied(DomainError):
    """Raised when an actor attempts something it is not authorized to do."""

    def __init__(self, reason: DenialReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail
