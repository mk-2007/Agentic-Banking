"""What every specialist agent needs: an identity, a way to call tools, and the trusted settings.

An agent never holds a bank connection. It owns a `ToolSession`, which sends each request through
the `ToolRegistry` under the agent's own role and case. Permission checks, case scoping and audit
therefore stay in the tool layer; nothing in this module can widen them.
"""

from dataclasses import dataclass, field

from nexa.config import DEFAULT_THRESHOLDS, FraudThresholds
from nexa.domain.actors import Actor, ActorKind, Role, SessionChannel
from nexa.domain.base import FlatDict, JsonDict
from nexa.domain.clock import Clock
from nexa.domain.errors import DomainError
from nexa.domain.tooling import ToolCall
from nexa.llm import LlmGateway
from nexa.tools import ToolRegistry


class AgentToolError(DomainError):
    """A tool refused or failed, so the agent cannot continue (orchestration decides what next)."""

    def __init__(self, tool_name: str, error_code: str, message: str = "") -> None:
        detail = f"{tool_name} failed with {error_code}"
        super().__init__(f"{detail}: {message}" if message else detail)
        self.tool_name = tool_name
        self.error_code = error_code


@dataclass(frozen=True)
class AgentContext:
    """Trusted settings shared by the agents working on one case.

    ``channel`` is required and has no default: it decides how much knowledge an agent may read,
    so trusted code must state it. ``gateway`` is optional; agents that use a model fall back to
    deterministic behaviour without one. ``investigate`` is the opt-in that puts the model-driven
    investigator into the analysis step; without it the analysis is the plain baseline.
    """

    registry: ToolRegistry
    clock: Clock
    channel: SessionChannel
    thresholds: FraudThresholds = DEFAULT_THRESHOLDS
    gateway: LlmGateway | None = None
    investigate: bool = False  # let the model investigate (needs a gateway), under a fact-checker


def agent_actor(role: Role) -> Actor:
    """Return the actor an agent with ``role`` acts as."""
    return Actor(kind=ActorKind.AGENT, id=f"{role.value}_1", role=role)


@dataclass
class ToolSession:
    """One agent's tool access for one case."""

    ctx: AgentContext
    role: Role
    case_id: str
    _calls: int = field(default=0, repr=False)

    def call(self, tool_name: str, arguments: FlatDict | None = None) -> JsonDict:
        """Run ``tool_name`` as this agent and return its output, or raise `AgentToolError`."""
        self._calls += 1
        call = ToolCall(
            id=f"{self.case_id}:{self.role.value}:{self._calls}",
            tool_name=tool_name,
            actor=agent_actor(self.role),
            case_id=self.case_id,
            arguments=arguments or {},
            channel=self.ctx.channel,
            requested_at=self.ctx.clock(),
        )
        result = self.ctx.registry.invoke(call)
        if not result.ok:
            raise AgentToolError(
                tool_name, result.error_code or "unknown", result.error_message or ""
            )
        return result.output
