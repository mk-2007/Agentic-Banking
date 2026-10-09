"""The decision contract: what a decision provider must hand back.

A `Decision` is a *recommendation*. It is never an authorization. Safety rules are
enforced by validators, so an unsafe decision cannot even be constructed:

- candidates are ranked best-first, and the recommendation is one of them;
- if the recommendation is not the top-ranked candidate, a hard gate must say why;
- with missing or conflicting evidence, only "ask for more / hand to a human" is allowed;
- consequential actions (Level 3+) need supporting evidence and a cited policy.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .actions import (
    ACTION_RISK_LEVEL,
    UNCERTAINTY_SAFE_ACTIONS,
    ActionType,
    RiskLevel,
)
from .base import Contract
from .evidence import PolicyRef


class UncertaintyFlag(StrEnum):
    """Reasons a decision should be treated with caution."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_DATA = "stale_data"
    LOW_MODEL_CONFIDENCE = "low_model_confidence"


# Flags that forbid recommending anything but a cautious action.
BLOCKING_UNCERTAINTY: frozenset[UncertaintyFlag] = frozenset(
    {UncertaintyFlag.INSUFFICIENT_EVIDENCE, UncertaintyFlag.CONFLICTING_EVIDENCE}
)


class CandidateScore(Contract):
    """One candidate action with its score and the evidence for and against it."""

    action: ActionType
    score: float = Field(ge=0.0, le=1.0, description="Ranking score, not a calibrated probability.")
    supporting_evidence_ids: tuple[str, ...] = ()
    opposing_evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_evidence_disjoint(self) -> Self:
        """Reject evidence that both supports and opposes an action."""
        overlap = set(self.supporting_evidence_ids) & set(self.opposing_evidence_ids)
        if overlap:
            raise ValueError(f"evidence cannot both support and oppose: {sorted(overlap)}")
        return self


class Decision(Contract):
    """A ranked recommendation for one case."""

    id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    ranked_candidates: tuple[CandidateScore, ...] = Field(min_length=1)
    recommended_action: ActionType
    overridden_by: str | None = Field(
        default=None,
        description="Name of the hard gate that replaced the top-ranked candidate, if any.",
    )
    risk_level: RiskLevel
    approval_required: bool
    uncertainty_flags: tuple[UncertaintyFlag, ...] = ()
    evidence_strength: float = Field(ge=0.0, le=1.0)
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_refs: tuple[PolicyRef, ...] = ()
    provider: str = Field(min_length=1, description="Which DecisionProvider produced this.")
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_ranking(self) -> Self:
        """Candidates are unique and sorted best-first; the recommendation is among them."""
        actions = [c.action for c in self.ranked_candidates]
        if len(set(actions)) != len(actions):
            raise ValueError("each action may appear only once in ranked_candidates")
        scores = [c.score for c in self.ranked_candidates]
        if scores != sorted(scores, reverse=True):
            raise ValueError("ranked_candidates must be sorted by score, highest first")
        if self.recommended_action not in actions:
            raise ValueError("recommended_action must be one of the ranked candidates")
        if self.recommended_action != actions[0] and not self.overridden_by:
            raise ValueError("recommending a lower-ranked action requires overridden_by")
        return self

    @model_validator(mode="after")
    def check_governance_fields(self) -> Self:
        """Risk level and approval flag must match the recommended action."""
        expected = ACTION_RISK_LEVEL[self.recommended_action]
        if self.risk_level != expected:
            raise ValueError(f"risk_level must be {expected.name} for {self.recommended_action}")
        if self.approval_required != expected.requires_human_approval:
            raise ValueError("approval_required does not match the risk level")
        return self

    @model_validator(mode="after")
    def check_uncertainty_rules(self) -> Self:
        """Missing or conflicting evidence forces a cautious recommendation."""
        blocked = BLOCKING_UNCERTAINTY & set(self.uncertainty_flags)
        if blocked and self.recommended_action not in UNCERTAINTY_SAFE_ACTIONS:
            names = sorted(f.value for f in blocked)
            raise ValueError(
                f"with {names}, only escalation or requests for information are allowed"
            )
        return self

    @model_validator(mode="after")
    def check_consequential_actions_are_justified(self) -> Self:
        """Level 3+ recommendations need supporting evidence and a cited policy."""
        if not self.risk_level.requires_human_approval:
            return self
        chosen = next(c for c in self.ranked_candidates if c.action == self.recommended_action)
        if not chosen.supporting_evidence_ids:
            raise ValueError("a consequential action needs supporting evidence")
        if not self.policy_refs:
            raise ValueError("a consequential action must cite at least one policy")
        return self
