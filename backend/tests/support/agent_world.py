"""Agents wired to the real simulated bank, tool registry and knowledge base (shared by tests)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from nexa.agents import AgentContext
from nexa.audit import AuditRecorder, InMemoryAuditLog
from nexa.bank_sim import load_bank, load_scenarios
from nexa.bank_sim.scenarios import ScenarioSpec
from nexa.domain.actors import SessionChannel
from nexa.domain.approval import ApprovalRequest, ApprovalVote
from nexa.domain.case import Case
from nexa.llm import LlmGateway
from nexa.rag import load_knowledge_base
from nexa.security import CaseScope
from nexa.tools import ToolContext, build_default_registry

NOW = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


class Scopes:
    def __init__(self) -> None:
        self.scopes: dict[str, CaseScope] = {}

    def get_scope(self, case_id: str) -> CaseScope | None:
        return self.scopes.get(case_id)


class NoApprovals:
    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        return None

    def get_votes(self, approval_id: str) -> list[ApprovalVote]:
        return []

    def try_consume(self, approval_id: str) -> bool:
        return False


@dataclass
class World:
    scopes: Scopes
    log: InMemoryAuditLog
    tools: ToolContext

    def context(
        self,
        channel: SessionChannel = SessionChannel.EMPLOYEE,
        gateway: LlmGateway | None = None,
    ) -> AgentContext:
        return AgentContext(
            registry=build_default_registry(self.tools),
            clock=lambda: NOW,
            channel=channel,
            gateway=gateway,
        )

    def case(self, scenario_id: str) -> Case:
        scenario = SCENARIOS[scenario_id]
        case = Case(id=f"case_{scenario_id}", alert=scenario.alert, created_at=NOW, updated_at=NOW)
        self.scopes.scopes[case.id] = CaseScope(
            case_id=case.id,
            customer_id=scenario.alert.customer_id,
            account_ids=(scenario.alert.account_id,),
        )
        return case


SCENARIOS: dict[str, ScenarioSpec] = {s.id: s for s in load_scenarios()}


def build_world() -> World:
    scopes, log = Scopes(), InMemoryAuditLog()
    tools = ToolContext(
        bank=load_bank(),
        scopes=scopes,
        approvals=NoApprovals(),
        knowledge=load_knowledge_base(),
        audit=AuditRecorder(log, clock=lambda: NOW),
        clock=lambda: NOW,
    )
    return World(scopes, log, tools)
