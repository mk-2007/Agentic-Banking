"""Tool contracts: what a tool declares about itself, and the call/result envelopes.

The tool layer (later phase) uses these to enforce permissions and auditing in code.
"""

import re
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .actions import RiskLevel
from .actors import Actor, Role
from .base import Contract, FlatDict

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolSpec(Contract):
    """A tool's declaration: purpose, risk, and who may call it."""

    name: str
    description: str = Field(min_length=1)
    risk_level: RiskLevel
    required_roles: tuple[Role, ...] = Field(min_length=1)
    read_only: bool

    @model_validator(mode="after")
    def check_spec(self) -> Self:
        """Names are snake_case; tools that change state are at least Level 2."""
        if not _TOOL_NAME.match(self.name):
            raise ValueError("tool name must be snake_case")
        if not self.read_only and self.risk_level < RiskLevel.LOW_OPERATIONAL:
            raise ValueError("a tool that changes state must be at least Level 2")
        return self


class ToolCall(Contract):
    """A request to run a tool, always attributed to an actor."""

    id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    actor: Actor
    case_id: str | None = None
    arguments: FlatDict = Field(default_factory=dict)
    approval_id: str | None = Field(
        default=None, description="Required by tools that execute approved actions."
    )
    requested_at: AwareDatetime


class ToolResult(Contract):
    """The outcome of a tool call: either output, or an error code and message."""

    call_id: str = Field(min_length=1)
    ok: bool
    output: FlatDict = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        """Successful results carry no error; failed results must carry an error code."""
        if self.ok and (self.error_code or self.error_message):
            raise ValueError("a successful result cannot carry an error")
        if not self.ok and not self.error_code:
            raise ValueError("a failed result needs an error_code")
        return self
