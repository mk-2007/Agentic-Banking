"""Model gateway: one interface over interchangeable model providers.

Why: Keeps the platform independent of any single vendor (PRD principle 8) and makes model calls
reliable, budgeted and validated.

Where it sits: Layer 1. Used by rag, decision and agents.

Modules:
    messages       provider-neutral request/response types
    provider       the `LlmProvider` interface
    openai_compat  one adapter for any OpenAI-compatible endpoint (Groq, Gemini)
    gateway        retries, failover, token budget, validated structured output
    usage          token/cost ledger with a per-case budget
    prompts        fencing for untrusted text
    factory        build a gateway from environment variables
    fake           a scripted provider for tests and offline demos
"""

from .errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    LlmAuthError,
    LlmError,
    LlmRequestError,
    StructuredOutputError,
    TransientLlmError,
)
from .factory import LlmConfigError, build_gateway, load_dotenv_file
from .fake import ScriptedProvider
from .gateway import LlmGateway, StructuredResult
from .messages import ChatMessage, LlmRequest, LlmResponse, Role, TokenUsage
from .prompts import wrap_untrusted
from .provider import LlmProvider
from .usage import UsageLedger, UsageSummary

__all__ = [
    "AllProvidersFailedError",
    "BudgetExceededError",
    "ChatMessage",
    "LlmAuthError",
    "LlmConfigError",
    "LlmError",
    "LlmGateway",
    "LlmProvider",
    "LlmRequest",
    "LlmRequestError",
    "LlmResponse",
    "Role",
    "ScriptedProvider",
    "StructuredOutputError",
    "StructuredResult",
    "TokenUsage",
    "TransientLlmError",
    "UsageLedger",
    "UsageSummary",
    "build_gateway",
    "load_dotenv_file",
    "wrap_untrusted",
]
