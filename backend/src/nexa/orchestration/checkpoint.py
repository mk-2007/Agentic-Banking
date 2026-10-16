"""Which types a saved case may be rebuilt from.

A checkpoint is data read back from storage and turned into Python objects. Rebuilding arbitrary
types from stored data is a code-execution risk, so we list the types a case can contain and let
the serializer refuse everything else. `tests/unit/orchestration` runs a whole case through a
checkpointer under this list, so adding a field to the state without listing its type fails a test.
"""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from nexa.agents import Dossier, PolicyResult, VerificationReport
from nexa.agents.dossier import (
    AccountFact,
    CustomerFact,
    KycFact,
    TransactionFact,
    TravelNoticeFact,
)
from nexa.agents.verification_agent import IssueCode, VerificationIssue
from nexa.domain.case import Alert, Case, CaseStatus
from nexa.domain.decision import UncertaintyFlag
from nexa.domain.evidence import Evidence, EvidenceKind, PolicyRef, SourceRef

_TYPES: tuple[type, ...] = (
    Case, Alert, CaseStatus,
    Evidence, EvidenceKind, SourceRef, PolicyRef,
    Dossier, TransactionFact, TravelNoticeFact, CustomerFact, AccountFact, KycFact,
    PolicyResult, VerificationReport, VerificationIssue, IssueCode, UncertaintyFlag,
)  # fmt: skip

ALLOWED_TYPES: tuple[tuple[str, str], ...] = tuple((t.__module__, t.__qualname__) for t in _TYPES)


def checkpoint_serde() -> JsonPlusSerializer:
    """Return a serializer that rebuilds only the types a case can contain."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_TYPES)
