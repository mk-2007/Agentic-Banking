"""The controlled tool layer between agents and the bank.

Why: Every tool declares schema, risk level and required role, and enforces permissions + audit
itself (PRD section 14).

Where it sits: Layer 2. The only door from agents to bank_sim and rag.

Modules:
    base       `Tool` and `ToolContext`
    registry   `ToolRegistry.invoke`: authorization, audit and error handling for every call
    read_tools five read-only tools with data minimization
    knowledge  `search_knowledge_base`: cited passages, clearance from role and channel
    execution  `execute_authorized_action`, the only tool that restricts an account
    case_actions `perform_case_action`, follow-ups such as watch, ask or escalate
"""

from .base import Tool, ToolContext
from .case_actions import PerformCaseAction
from .execution import ExecuteAuthorizedAction, TransientBankError
from .knowledge import SearchKnowledgeBase
from .read_tools import (
    GetAccountDetails,
    GetCustomerProfile,
    GetKycStatus,
    GetTransactionDetails,
    GetTransactionHistory,
)
from .reconciliation import Mismatch, reconcile
from .registry import ToolRegistry


def build_default_registry(ctx: ToolContext) -> ToolRegistry:
    """Create a registry holding every standard tool, checked against the permission matrix."""
    registry = ToolRegistry(ctx)
    for tool in (
        GetCustomerProfile(),
        GetAccountDetails(),
        GetTransactionDetails(),
        GetTransactionHistory(),
        GetKycStatus(),
        SearchKnowledgeBase(),
        ExecuteAuthorizedAction(),
        PerformCaseAction(),
    ):
        registry.register(tool)
    registry.assert_complete()
    return registry


__all__ = [
    "Mismatch",
    "TransientBankError",
    "reconcile",
    "ExecuteAuthorizedAction",
    "GetAccountDetails",
    "GetCustomerProfile",
    "GetKycStatus",
    "GetTransactionDetails",
    "GetTransactionHistory",
    "PerformCaseAction",
    "SearchKnowledgeBase",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "build_default_registry",
]
