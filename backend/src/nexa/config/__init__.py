"""Settings, per-bank thresholds and the approval matrix.

Why: Bank-specific behaviour must be configuration, not hard-coded logic (PRD section 49).

Where it sits: Layer 0/1. Depends only on domain.

Modules:
    thresholds       fraud and KYC limits (mirrored in the policy documents)
    approval_matrix  required approver roles and expiry per action
    tool_permissions which roles may call which tools (deny by default)
    rag_access       role and channel clearance for knowledge retrieval
    llm              provider presets, JSON modes and reliability/budget limits
"""

from .approval_matrix import APPROVAL_MATRIX, ApprovalRule, approval_rule_for
from .llm import DEFAULT_LIMITS, PRESETS, JsonMode, LlmLimits, ProviderPreset
from .rag_access import CHANNEL_CAP, ROLE_CLEARANCE, effective_clearance
from .thresholds import DEFAULT_THRESHOLDS, FraudThresholds
from .tool_permissions import TOOL_ROLES, roles_for

__all__ = [
    "APPROVAL_MATRIX",
    "CHANNEL_CAP",
    "DEFAULT_LIMITS",
    "DEFAULT_THRESHOLDS",
    "ROLE_CLEARANCE",
    "TOOL_ROLES",
    "ApprovalRule",
    "FraudThresholds",
    "JsonMode",
    "LlmLimits",
    "PRESETS",
    "ProviderPreset",
    "approval_rule_for",
    "effective_clearance",
    "roles_for",
]
