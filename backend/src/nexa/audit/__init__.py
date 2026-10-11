"""Append-only audit log of every meaningful event.

Why: Lets us reconstruct exactly how a decision was reached (PRD principle 7, section 26).

Where it sits: Layer 1. Written to by tools, approvals and orchestration.

Modules:
    log       `InMemoryAuditLog` and `JsonlAuditLog` over the domain hash chain
    recorder  `AuditRecorder`, which fills in ids and timestamps
"""

from .log import AuditLog, AuditTamperedError, InMemoryAuditLog, JsonlAuditLog
from .recorder import AuditRecorder

__all__ = [
    "AuditLog",
    "AuditRecorder",
    "AuditTamperedError",
    "InMemoryAuditLog",
    "JsonlAuditLog",
]
