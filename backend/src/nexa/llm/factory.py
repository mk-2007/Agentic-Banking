"""Build a gateway from environment variables (and an optional ``.env`` file).

Providers are listed in ``NEXA_LLM_PROVIDERS`` (default ``groq,gemini``), first one is primary.
A provider is used only if its API key is present, so having just one key works. API keys are
read from the environment and are never logged, printed or written anywhere.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from nexa.config.llm import DEFAULT_LIMITS, PRESETS, LlmLimits

from .errors import LlmError
from .gateway import LlmGateway
from .openai_compat import OpenAiCompatibleProvider
from .provider import LlmProvider
from .usage import UsageLedger

DEFAULT_PROVIDERS = "groq,gemini"


class LlmConfigError(LlmError):
    """Raised when no usable provider is configured."""


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Read ``KEY=VALUE`` lines from ``path`` (comments and blank lines ignored)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def build_providers(
    env: Mapping[str, str],
    *,
    limits: LlmLimits = DEFAULT_LIMITS,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> list[LlmProvider]:
    """Create a provider for each listed name whose API key is set."""
    names = [n.strip().lower() for n in env.get("NEXA_LLM_PROVIDERS", DEFAULT_PROVIDERS).split(",")]
    providers: list[LlmProvider] = []
    for name in filter(None, names):
        if name not in PRESETS:
            raise LlmConfigError(f"unknown provider '{name}'; choose from {sorted(PRESETS)}")
        preset = PRESETS[name]
        key = env.get(preset.api_key_env, "").strip()
        if not key:
            continue
        providers.append(
            OpenAiCompatibleProvider(
                name=preset.name,
                base_url=preset.base_url,
                api_key=key,
                model=env.get(preset.model_env, "").strip() or preset.default_model,
                json_mode=preset.json_mode,
                timeout_seconds=limits.request_timeout_seconds,
                client=client_factory() if client_factory else None,
            )
        )
    return providers


def build_gateway(
    env: Mapping[str, str],
    *,
    limits: LlmLimits = DEFAULT_LIMITS,
    ledger: UsageLedger | None = None,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> LlmGateway:
    """Create a gateway from ``env``, or raise `LlmConfigError` with setup instructions."""
    providers = build_providers(env, limits=limits, client_factory=client_factory)
    if not providers:
        needed = ", ".join(p.api_key_env for p in PRESETS.values())
        raise LlmConfigError(f"no provider is configured. Set at least one API key ({needed}).")
    return LlmGateway(providers, limits=limits, ledger=ledger)
