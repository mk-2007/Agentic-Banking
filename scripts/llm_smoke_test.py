#!/usr/bin/env python3
"""Try your real API keys end to end. Needs `pip install -e backend` first.

    python scripts/llm_smoke_test.py --list-models   # which models can my keys use today?
    python scripts/llm_smoke_test.py                 # one validated structured call per provider

Keys come from the environment or from a `.env` file in the repository root (never committed).
Nothing here prints or logs a key.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Literal

import httpx

from nexa.config.llm import DEFAULT_LIMITS, PRESETS
from nexa.domain.base import Contract
from nexa.llm import (
    ChatMessage,
    LlmError,
    LlmRequest,
    Role,
    build_gateway,
    load_dotenv_file,
)

ROOT = Path(__file__).resolve().parents[1]


class Verdict(Contract):
    """A tiny schema to prove structured output works."""

    label: Literal["ok", "suspicious"]
    reason: str


def environment() -> dict[str, str]:
    """Merge the repository's .env (if any) with real environment variables."""
    return {**load_dotenv_file(ROOT / ".env"), **os.environ}


def list_models(env: dict[str, str]) -> int:
    found = False
    for name, preset in PRESETS.items():
        key = env.get(preset.api_key_env, "").strip()
        if not key:
            print(f"{name}: no key ({preset.api_key_env} not set), skipped")
            continue
        found = True
        url = preset.base_url.rstrip("/") + "/models"
        try:
            response = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
            response.raise_for_status()
            ids = sorted(m.get("id", "?") for m in response.json().get("data", []))
        except (httpx.HTTPError, ValueError) as error:
            print(f"{name}: could not list models ({type(error).__name__})")
            continue
        current = env.get(preset.model_env) or preset.default_model
        print(f"\n{name} (using: {current}; override with {preset.model_env}):")
        for model_id in ids:
            print(f"  {model_id}")
    if not found:
        print("No API keys found. Set GROQ_API_KEY and/or GEMINI_API_KEY (see .env.example).")
        return 1
    return 0


def smoke(env: dict[str, str]) -> int:
    failures = 0
    for name, preset in PRESETS.items():
        if not env.get(preset.api_key_env, "").strip():
            print(f"{name}: no key, skipped")
            continue
        gateway = build_gateway({**env, "NEXA_LLM_PROVIDERS": name}, limits=DEFAULT_LIMITS)
        request = LlmRequest(
            messages=(
                ChatMessage(
                    role=Role.USER,
                    content=(
                        "Classify this payment: PKR 4,200 at a grocery store in the customer's "
                        "home city, paid by card from a trusted device."
                    ),
                ),
            ),
        )
        try:
            result = gateway.structured(request, Verdict, case_id="smoke")
        except LlmError as error:
            failures += 1
            print(f"{name}: FAILED - {error}")
            continue
        response = result.response
        print(
            f"{name}: OK model={response.model} label={result.value.label} "
            f"tokens={result.usage.total} latency={response.latency_ms}ms repairs={result.repairs}"
        )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the model gateway with real keys.")
    parser.add_argument("--list-models", action="store_true", help="list models each key can use")
    args = parser.parse_args()
    env = environment()
    return list_models(env) if args.list_models else smoke(env)


if __name__ == "__main__":
    sys.exit(main())
