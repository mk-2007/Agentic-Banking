"""Model provider presets and limits, as configuration.

Model names change often, so each preset has a *default* that can be overridden with an
environment variable. Run ``python scripts/llm_smoke_test.py --list-models`` to see what your
key can use today, then set ``NEXA_GROQ_MODEL`` or ``NEXA_GEMINI_MODEL``.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import Field

from nexa.domain.base import Contract


class JsonMode(StrEnum):
    """How to ask a provider for JSON. Responses are always validated regardless of the mode."""

    JSON_OBJECT = "json_object"  # response_format={"type": "json_object"}
    JSON_SCHEMA = "json_schema"  # response_format with a schema (supported by fewer models)
    NONE = "none"  # rely on the prompt alone


class ProviderPreset(Contract):
    """Connection details for one OpenAI-compatible provider."""

    name: str
    base_url: str
    api_key_env: str
    model_env: str
    default_model: str
    json_mode: JsonMode = JsonMode.JSON_OBJECT


PRESETS: Final[Mapping[str, ProviderPreset]] = MappingProxyType(
    {
        "groq": ProviderPreset(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            model_env="NEXA_GROQ_MODEL",
            default_model="openai/gpt-oss-20b",
        ),
        # Claude through Anthropic's OpenAI-compatible endpoint. Not in the default order, so it is
        # only used (and only costs anything) when named in NEXA_LLM_PROVIDERS. That endpoint does
        # not honour JSON mode, so the gateway relies on its own validation, as it always does.
        "anthropic": ProviderPreset(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_env="ANTHROPIC_API_KEY",
            model_env="NEXA_ANTHROPIC_MODEL",
            default_model="claude-haiku-5-5",
            json_mode=JsonMode.NONE,
        ),
        "gemini": ProviderPreset(
            name="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key_env="GEMINI_API_KEY",
            model_env="NEXA_GEMINI_MODEL",
            default_model="gemini-flash-latest",
        ),
    }
)

# USD per one million tokens: (input, output). Unlisted models count as free-tier (cost 0).
MODEL_PRICES_USD_PER_MILLION: Final[Mapping[str, tuple[float, float]]] = MappingProxyType({})


class LlmLimits(Contract):
    """Reliability and budget limits for the gateway."""

    max_attempts_per_provider: int = Field(default=3, ge=1, le=6)
    backoff_seconds: float = Field(default=1.0, ge=0.0)
    max_backoff_seconds: float = Field(default=20.0, ge=0.0)
    request_timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_repairs: int = Field(default=2, ge=0, le=4, description="Re-asks after invalid JSON.")
    default_max_tokens: int = Field(
        default=2048,
        ge=256,
        description="Generous on purpose: reasoning models spend tokens thinking.",
    )
    case_token_budget: int = Field(
        default=60_000, ge=1_000, description="Most tokens one case may use across all calls."
    )


DEFAULT_LIMITS = LlmLimits()
