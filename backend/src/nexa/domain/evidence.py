"""Evidence: structured facts an investigation is built on.

Every claim the platform makes must trace back to a piece of `Evidence`, and every piece
of evidence must say where it came from: a tool result or a versioned policy clause.
Text inside evidence (merchant names, notes) is *untrusted data*, never instructions.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .base import Contract, FlatDict


class EvidenceKind(StrEnum):
    """What aspect of the case a piece of evidence describes."""

    TRANSACTION = "transaction"
    CUSTOMER_PROFILE = "customer_profile"
    ACCOUNT_STATE = "account_state"
    BEHAVIOUR_PATTERN = "behaviour_pattern"
    KYC_STATUS = "kyc_status"
    POLICY_CLAUSE = "policy_clause"


class PolicyRef(Contract):
    """Pointer to a specific version of a policy document."""

    doc_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    section: str | None = None


class SourceRef(Contract):
    """Where a piece of evidence came from: a tool record or a policy clause (or both)."""

    tool_name: str | None = None
    record_id: str | None = None
    policy: PolicyRef | None = None

    @model_validator(mode="after")
    def check_has_provenance(self) -> Self:
        """Require a tool record, a policy clause, or both; never nothing."""
        has_tool_record = self.tool_name is not None and self.record_id is not None
        half_tool_record = (self.tool_name is None) != (self.record_id is None)
        if half_tool_record:
            raise ValueError("tool_name and record_id must be given together")
        if not has_tool_record and self.policy is None:
            raise ValueError("a source needs a tool record or a policy reference")
        return self


class Evidence(Contract):
    """One traceable fact collected during an investigation."""

    id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    kind: EvidenceKind
    summary: str = Field(min_length=1)
    data: FlatDict = Field(default_factory=dict)
    source: SourceRef
    collected_at: AwareDatetime
