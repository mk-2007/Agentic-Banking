"""The tool abstraction: what a tool is, and what it is given when it runs.

A tool is the *only* way an agent touches the bank. Each tool declares a `ToolSpec` (name, risk
level, allowed roles taken from configuration) and implements `run`. Authorization, auditing and
error handling are done by the `ToolRegistry`, so a tool contains only its own logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from nexa.audit import AuditRecorder
from nexa.bank_sim.gateway import BankGateway
from nexa.domain.base import JsonDict
from nexa.domain.clock import Clock
from nexa.domain.evidence import PolicyRef
from nexa.domain.tooling import ToolCall, ToolSpec
from nexa.rag import KnowledgeSearch
from nexa.security import ApprovalSource, CaseScopeProvider, check_scope


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may use. Built once and shared by the registry."""

    bank: BankGateway
    scopes: CaseScopeProvider
    approvals: ApprovalSource
    knowledge: KnowledgeSearch
    audit: AuditRecorder
    clock: Clock

    def require_scope(
        self,
        call: ToolCall,
        *,
        customer_id: str | None = None,
        account_id: str | None = None,
    ) -> None:
        """Raise `AuthorizationDenied` unless the call may touch these records."""
        check_scope(
            self.scopes, call.actor, call.case_id, customer_id=customer_id, account_id=account_id
        ).raise_if_denied()


class Tool(ABC):
    """Base class for every tool."""

    spec: ClassVar[ToolSpec]

    @abstractmethod
    def run(self, call: ToolCall, ctx: ToolContext) -> JsonDict:
        """Perform the tool's work and return its output.

        Tools validate their own arguments (a failure becomes ``invalid_arguments``), call
        ``ctx.require_scope`` for the records they touch, and raise `AuthorizationDenied`
        for anything not allowed. They never write audit events about the call itself; the
        registry does.
        """

    def policy_refs(self, output: JsonDict) -> tuple[PolicyRef, ...]:
        """Return the policy documents ``output`` was drawn from, for the audit record."""
        return ()
