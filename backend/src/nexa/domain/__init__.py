"""Pure data models and rules shared by every layer.

Why: Single source of truth for what a Case, Decision, Action or Evidence *is*. Contains no
I/O and imports nothing else from nexa, so any layer can depend on it safely.

Where it sits: Layer 0 (bottom). Everything may import it; it imports nothing.

Modules:
    actions   closed set of actions + risk levels
    actors    roles and actors (human / agent / system)
    evidence  traceable facts and their sources
    case      the case and its state machine
    decision  ranked recommendation with safety invariants
    approval  approval requests, votes and the evaluation rule
    tooling   tool declarations, calls and results
    clock     injectable time source
    knowledge documents, chunks, sensitivity and retrieval hits
    audit     tamper-evident hash-chained audit events
"""

from .actions import ACTION_RISK_LEVEL, ActionType, RiskLevel
from .actors import Actor, ActorKind, Role, SessionChannel
from .approval import ApprovalRequest, ApprovalStatus, ApprovalVote, Verdict, evaluate_approval
from .audit import AuditDraft, AuditEvent, AuditEventType, first_broken_link, seal
from .case import Alert, Case, CaseStatus
from .clock import Clock, utc_now
from .decision import CandidateScore, Decision, UncertaintyFlag
from .errors import DomainError, InvalidTransitionError
from .evidence import Evidence, EvidenceKind, PolicyRef, SourceRef
from .knowledge import Chunk, DocumentMeta, DocumentStatus, RetrievalHit, Sensitivity
from .tooling import ToolCall, ToolResult, ToolSpec

__all__ = [
    "ACTION_RISK_LEVEL",
    "ActionType",
    "Actor",
    "ActorKind",
    "Alert",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalVote",
    "AuditDraft",
    "AuditEvent",
    "AuditEventType",
    "CandidateScore",
    "Chunk",
    "Clock",
    "Case",
    "CaseStatus",
    "Decision",
    "DocumentMeta",
    "DocumentStatus",
    "DomainError",
    "Evidence",
    "EvidenceKind",
    "InvalidTransitionError",
    "PolicyRef",
    "RetrievalHit",
    "RiskLevel",
    "Role",
    "Sensitivity",
    "SessionChannel",
    "SourceRef",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "UncertaintyFlag",
    "Verdict",
    "evaluate_approval",
    "first_broken_link",
    "seal",
    "utc_now",
]
