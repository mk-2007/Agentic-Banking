"""Connects a `DecisionProvider` to the graph's decision step.

The graph hands over an investigation; a provider wants a narrow, typed request. This adapter makes
that request from the verified findings, the verifier's uncertainty flags and the cited policy
clauses, and nothing else, so a provider can never see the dossier, the bank or third-party text.
"""

from nexa.agents import Investigation
from nexa.decision import DecisionProvider, DecisionRequest
from nexa.domain.case import Case
from nexa.domain.decision import Decision

from .nodes import DecisionSource


def provider_source(provider: DecisionProvider) -> DecisionSource:
    """Return a graph decision source backed by ``provider``."""

    def source(case: Case, investigation: Investigation) -> Decision:
        return provider.decide(
            DecisionRequest(
                case_id=case.id,
                findings=investigation.findings,
                uncertainty_flags=investigation.verification.uncertainty_flags,
                policy_refs=investigation.policy.policy_refs,
            )
        )

    return source
