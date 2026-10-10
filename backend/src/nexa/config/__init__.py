"""Settings, per-bank thresholds and the approval matrix.

Why: Bank-specific behaviour must be configuration, not hard-coded logic (PRD section 49).

Where it sits: Layer 0/1. Depends only on domain.

Modules:
    thresholds       fraud and KYC limits (mirrored in the policy documents)
    approval_matrix  required approver roles and expiry per action
"""

from .approval_matrix import APPROVAL_MATRIX, ApprovalRule, approval_rule_for
from .thresholds import DEFAULT_THRESHOLDS, FraudThresholds

__all__ = [
    "APPROVAL_MATRIX",
    "DEFAULT_THRESHOLDS",
    "ApprovalRule",
    "FraudThresholds",
    "approval_rule_for",
]
