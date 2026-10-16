"""The decision provider interface: typed findings in, a validated `Decision` out.

A provider sees evidence objects, the verifier's uncertainty flags and the policy clauses that were
found. It never sees the bank, a session or free text from third parties. Whatever it returns is a
recommendation: `Decision` refuses to be built unsafely, and execution still needs a human approval.
"""

from typing import Protocol

from pydantic import Field

from nexa.domain.base import Contract
from nexa.domain.decision import Decision, UncertaintyFlag
from nexa.domain.evidence import Evidence, PolicyRef


class DecisionRequest(Contract):
    """Everything a provider may use to decide one case."""

    case_id: str = Field(min_length=1)
    findings: tuple[Evidence, ...] = ()
    uncertainty_flags: tuple[UncertaintyFlag, ...] = ()
    policy_refs: tuple[PolicyRef, ...] = ()


class DecisionProvider(Protocol):
    """Anything that can turn a `DecisionRequest` into a `Decision` (rules, an LLM, JEV later)."""

    name: str

    def decide(self, request: DecisionRequest) -> Decision:
        """Return a ranked recommendation for ``request.case_id``."""
        ...
