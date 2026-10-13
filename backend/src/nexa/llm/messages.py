"""Provider-neutral request and response types."""

from enum import StrEnum

from pydantic import Field

from nexa.domain.base import Contract


class Role(StrEnum):
    """Who wrote a chat message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Contract):
    """One message in a conversation."""

    role: Role
    content: str


class TokenUsage(Contract):
    """Tokens used by one call."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    @property
    def total(self) -> int:
        """Prompt plus completion tokens."""
        return self.prompt_tokens + self.completion_tokens


class LlmRequest(Contract):
    """What to ask a model."""

    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    max_tokens: int = Field(default=2048, ge=16, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    json_output: bool = False
    json_schema: dict[str, object] | None = None


class LlmResponse(Contract):
    """What a model returned."""

    text: str
    usage: TokenUsage
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    finish_reason: str | None = None
