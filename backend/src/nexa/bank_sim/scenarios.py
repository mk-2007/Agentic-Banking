"""Predefined evaluation scenarios (PRD section 44) as data.

A scenario names the alert that opens a case and states what a *correct* handling looks
like. The evaluation harness (a later phase) runs the platform on each scenario and
compares the outcome with `ExpectedOutcome`. Scenarios A-E come from the PRD; F and X are
additions that exercise the Level 4 approval flow and prompt-injection defence.
"""

from typing import Self

from pydantic import Field, model_validator

from nexa.domain.actions import ActionType
from nexa.domain.actors import Role
from nexa.domain.base import Contract
from nexa.domain.case import Alert


class ExpectedOutcome(Contract):
    """What correct handling of a scenario looks like."""

    acceptable_actions: tuple[ActionType, ...] = ()
    forbidden_actions: tuple[ActionType, ...] = ()
    must_involve_human: bool
    authorization_must_block: bool = False
    required_findings: tuple[str, ...] = Field(
        default=(), description="Facts a correct investigation must surface."
    )

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """Require disjoint action sets, and an acceptable set unless authorization is the test."""
        if set(self.acceptable_actions) & set(self.forbidden_actions):
            raise ValueError("an action cannot be both acceptable and forbidden")
        if not self.authorization_must_block and not self.acceptable_actions:
            raise ValueError(
                "a scenario that is not an authorization test needs acceptable actions"
            )
        return self


class UnauthorizedAttempt(Contract):
    """An action attempt that the authorization layer must refuse (scenario E)."""

    actor_role: Role
    attempted_action: ActionType
    account_id: str = Field(min_length=1)


class ScenarioSpec(Contract):
    """One evaluation scenario."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prd_ref: str = Field(min_length=1)
    description: str = Field(min_length=1)
    alert: Alert
    expected: ExpectedOutcome
    attempt: UnauthorizedAttempt | None = None
    contains_untrusted_instruction_text: bool = False

    @model_validator(mode="after")
    def check_attempt_matches_expectation(self) -> Self:
        """Require an unauthorized attempt exactly when authorization must block."""
        if (self.attempt is not None) != self.expected.authorization_must_block:
            raise ValueError("attempt and expected.authorization_must_block must go together")
        return self
