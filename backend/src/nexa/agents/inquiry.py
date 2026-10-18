"""What a model-driven investigation left behind, as typed data in a closed vocabulary.

The report is for people and for evaluation: which lookups the investigator made, which findings
it claimed, which of them held up, and where it and the deterministic baseline disagreed. It holds
codes, counts and tool names only, never merchant names, memos or model prose.
"""

from enum import StrEnum

from pydantic import Field

from nexa.domain.base import Contract


class InquiryOutcome(StrEnum):
    """How the investigator's run ended."""

    CONCLUDED = "concluded"  # it reported findings
    OUT_OF_STEPS = "out_of_steps"  # it kept asking and never concluded
    MODEL_UNAVAILABLE = "model_unavailable"  # missing, down, over budget or answered badly


class TraceStep(Contract):
    """One lookup the investigator asked for."""

    step: int = Field(ge=1)
    tool: str
    ok: bool = Field(description="False when the tool layer refused or failed the lookup.")
    error_code: str | None = None
    observation: str | None = Field(default=None, description="The id the answer was stored under.")


class DroppedClaim(Contract):
    """A claim the fact-checker refused, and why."""

    code: str
    reason: str = Field(description="uncited, unknown_observation or unsupported")


class InquiryReport(Contract):
    """The outcome of one investigation, ready to show and to score."""

    outcome: InquiryOutcome
    trace: tuple[TraceStep, ...] = ()
    claimed: tuple[str, ...] = Field(default=(), description="Finding codes the model claimed.")
    confirmed: tuple[str, ...] = Field(
        default=(), description="Claimed codes the baseline analysis also found from what it saw."
    )
    added: tuple[str, ...] = Field(
        default=(), description="Codes only the model found, confirmed by code, now findings."
    )
    dropped: tuple[DroppedClaim, ...] = ()
    missed: tuple[str, ...] = Field(
        default=(), description="Risk codes the baseline found that the model did not claim."
    )
    tokens: int = Field(default=0, ge=0)
    repairs: int = Field(default=0, ge=0)
    provider: str | None = None

    def audit_line(self) -> str:
        """Return a one-line summary for the audit log (counts and a closed vocabulary only)."""
        return (
            f"inquiry:{self.outcome.value} lookups={len(self.trace)} claimed={len(self.claimed)} "
            f"confirmed={len(self.confirmed)} added={len(self.added)} "
            f"dropped={len(self.dropped)} missed={len(self.missed)}"
        )
