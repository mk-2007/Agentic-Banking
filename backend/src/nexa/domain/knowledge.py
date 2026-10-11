"""Knowledge contracts: documents, chunks and what retrieval returns.

Metadata follows the NexaBank knowledge base, section 19.2, plus one addition, `sensitivity`,
which decides who may ever see a chunk. Sensitivity is ordered, so "may see up to INTERNAL" is a
single comparison.
"""

from datetime import date
from enum import IntEnum, StrEnum

from pydantic import Field

from .base import Contract
from .evidence import PolicyRef


class Sensitivity(IntEnum):
    """How widely a piece of knowledge may be shared."""

    PUBLIC = 0  # safe to show customers
    INTERNAL = 1  # employees and internal agents only
    RESTRICTED = 2  # detection logic, thresholds: named investigator roles only


class DocumentStatus(StrEnum):
    """Lifecycle of a document version (KB section 19.1)."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"
    RETIRED = "retired"


class DocumentMeta(Contract):
    """Document-level metadata attached to every chunk of the document."""

    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    department: str
    document_type: str
    version: str = Field(min_length=1)
    effective_date: date
    status: DocumentStatus
    access_level: str
    product: str
    jurisdiction: str
    sensitivity: Sensitivity


class Chunk(Contract):
    """A retrievable piece of a document, with its place in the document."""

    id: str = Field(min_length=1)
    meta: DocumentMeta
    section: str = Field(description="Section number such as '10.2', or '' for the preamble.")
    heading_path: tuple[str, ...]
    text: str = Field(min_length=1)

    def policy_ref(self) -> PolicyRef:
        """Return a citation for this chunk (document, version and section)."""
        return PolicyRef(
            doc_id=self.meta.document_id,
            version=self.meta.version,
            section=self.section or None,
        )


class RetrievalHit(Contract):
    """One ranked search result."""

    chunk: Chunk
    score: float
    rank: int = Field(ge=1)
