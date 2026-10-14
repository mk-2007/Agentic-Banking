"""A straight-line run of the four specialists on one case.

Why: gives the evaluation and the demo one call that exercises every agent. It is not the
orchestrator. Phase 6 replaces it with a graph that adds planning, loop limits, retries and the
human approval pause; the agents themselves do not change.
"""

from dataclasses import dataclass

from nexa.domain.case import Case
from nexa.domain.evidence import Evidence

from .analysis_agent import AnalysisAgent
from .base import AgentContext
from .data_agent import DataAgent
from .dossier import Dossier
from .policy_agent import PolicyAgent, PolicyResult
from .verification_agent import VerificationAgent, VerificationReport


@dataclass(frozen=True)
class Investigation:
    """Everything the specialists produced for one case."""

    dossier: Dossier
    findings: tuple[Evidence, ...]
    policy: PolicyResult
    verification: VerificationReport

    @property
    def all_evidence(self) -> tuple[Evidence, ...]:
        """Every piece of evidence, in the order it was gathered."""
        return (*self.dossier.evidence, *self.findings, *self.policy.evidence)


def investigate(case: Case, ctx: AgentContext) -> Investigation:
    """Run data, analysis, policy and verification agents in order on ``case``."""
    dossier = DataAgent(ctx).gather(case)
    findings = AnalysisAgent(ctx).analyze(case, dossier)
    policy = PolicyAgent(ctx).research(case, findings)
    verification = VerificationAgent(ctx.thresholds).verify(case, dossier, findings, policy)
    return Investigation(dossier, findings, policy, verification)
