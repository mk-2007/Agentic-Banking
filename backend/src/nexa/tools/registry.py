"""The tool registry: the single entry point for every tool call.

`invoke` is where the platform's guarantees are enforced, in this order:

1. unknown tool -> denied (deny by default)
2. role not allowed for this tool -> denied
3. agents must name a case -> denied otherwise
4. audit "tool called" **before** running (so even a crash leaves a trace)
5. validate arguments, run the tool (which applies case scope / approval checks)
6. audit "tool completed" or "tool denied", with hashes instead of raw data

Every outcome, success, denial or error, returns a `ToolResult` and leaves audit events.
"""

from pydantic import ValidationError

from nexa.bank_sim.errors import RecordNotFoundError
from nexa.config import TOOL_ROLES, roles_for
from nexa.domain.actors import ActorKind
from nexa.domain.audit import AuditEventType
from nexa.domain.base import JsonDict
from nexa.domain.errors import DomainError
from nexa.domain.hashing import sha256_hex
from nexa.domain.tooling import ToolCall, ToolResult
from nexa.security import AuthorizationDecision, AuthorizationDenied, DenialReason, authorize_role

from .base import Tool, ToolContext


class ToolRegistry:
    """Holds tools and runs them under authorization and audit."""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add ``tool``, checking it matches the permission matrix in configuration."""
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        if name not in TOOL_ROLES:
            raise ValueError(f"tool {name} has no entry in the permission matrix")
        if tool.spec.required_roles != roles_for(name):
            raise ValueError(f"tool {name} declares roles that differ from the configuration")
        self._tools[name] = tool

    def assert_complete(self) -> None:
        """Raise if the permission matrix lists a tool that was never registered."""
        missing = set(TOOL_ROLES) - set(self._tools)
        if missing:
            raise ValueError(
                f"tools in the permission matrix but not registered: {sorted(missing)}"
            )

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Names of all registered tools."""
        return tuple(sorted(self._tools))

    def invoke(self, call: ToolCall) -> ToolResult:
        """Run ``call`` under authorization and audit, and return its result."""
        tool = self._tools.get(call.tool_name)
        if tool is None:
            return self._deny(call, AuthorizationDecision.deny(DenialReason.UNKNOWN_TOOL))

        decision = authorize_role(call.actor, tool.spec.required_roles)
        if not decision.allowed:
            return self._deny(call, decision)
        if call.actor.kind is ActorKind.AGENT and call.case_id is None:
            return self._deny(
                call,
                AuthorizationDecision.deny(DenialReason.CASE_REQUIRED, "agents must name a case"),
            )

        input_hash = sha256_hex({"arguments": call.arguments, "approval_id": call.approval_id})
        self._record(AuditEventType.TOOL_CALLED, call, input_hash=input_hash, detail="started")
        try:
            output = tool.run(call, self._ctx)
        except AuthorizationDenied as denied:
            return self._deny(
                call, AuthorizationDecision.deny(denied.reason, denied.detail), input_hash
            )
        except ValidationError:
            return self._fail(call, "invalid_arguments", "arguments failed validation", input_hash)
        except RecordNotFoundError as missing:
            return self._fail(call, "not_found", str(missing), input_hash)
        except DomainError as error:
            return self._fail(call, "domain_error", str(error), input_hash)
        except Exception as error:  # noqa: BLE001 - a tool bug must never crash the platform
            return self._fail(call, "internal_error", type(error).__name__, input_hash)
        return self._succeed(call, output, input_hash)

    # --- outcomes -----------------------------------------------------
    def _deny(
        self, call: ToolCall, decision: AuthorizationDecision, input_hash: str | None = None
    ) -> ToolResult:
        reason = decision.reason or DenialReason.ROLE_NOT_PERMITTED
        self._record(
            AuditEventType.TOOL_DENIED,
            call,
            input_hash=input_hash,
            detail=f"{reason.value}: {decision.detail}" if decision.detail else reason.value,
        )
        return ToolResult(
            call_id=call.id,
            ok=False,
            error_code=reason.value,
            error_message=decision.detail or None,
        )

    def _fail(self, call: ToolCall, code: str, message: str, input_hash: str) -> ToolResult:
        self._record(
            AuditEventType.TOOL_COMPLETED, call, input_hash=input_hash, detail=f"failed: {code}"
        )
        return ToolResult(call_id=call.id, ok=False, error_code=code, error_message=message)

    def _succeed(self, call: ToolCall, output: JsonDict, input_hash: str) -> ToolResult:
        self._record(
            AuditEventType.TOOL_COMPLETED,
            call,
            input_hash=input_hash,
            output_ref=f"sha256:{sha256_hex(output)}",
            detail="ok",
        )
        return ToolResult(call_id=call.id, ok=True, output=output)

    def _record(
        self,
        event_type: AuditEventType,
        call: ToolCall,
        *,
        input_hash: str | None = None,
        output_ref: str | None = None,
        detail: str = "",
    ) -> None:
        self._ctx.audit.record(
            event_type,
            call.actor,
            case_id=call.case_id,
            tool_name=call.tool_name,
            input_hash=input_hash,
            output_ref=output_ref,
            detail=detail,
        )
