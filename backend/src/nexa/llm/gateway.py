"""The model gateway: reliable, budgeted, validated access to one or more model providers.

What it adds on top of a raw provider:

- **Retries** with exponential backoff on transient failures (rate limits, timeouts, 5xx,
  empty answers);
- **Failover** to the next provider when one is down, out of quota, or rejects the key;
- **A per-case token budget**, checked before every call, so a looping agent cannot burn money;
- **Structured output**: ask for JSON matching a Pydantic schema, validate it ourselves, and if the
  model slips (fences, extra fields, wrong types) show it the exact error and ask again.

Models are never trusted to return valid JSON; the gateway makes sure the caller only ever receives
validated objects.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from nexa.config.llm import DEFAULT_LIMITS, LlmLimits

from .errors import (
    AllProvidersFailedError,
    LlmAuthError,
    LlmError,
    LlmRequestError,
    StructuredOutputError,
    TransientLlmError,
)
from .messages import ChatMessage, LlmRequest, LlmResponse, Role, TokenUsage
from .provider import LlmProvider
from .usage import UsageLedger

log = logging.getLogger("nexa.llm")
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """A validated object plus how it was obtained."""

    value: T
    response: LlmResponse
    repairs: int
    usage: TokenUsage


class LlmGateway:
    """Calls providers in order, with retries, failover, budgets and validation."""

    def __init__(
        self,
        providers: Sequence[LlmProvider],
        *,
        ledger: UsageLedger | None = None,
        limits: LlmLimits = DEFAULT_LIMITS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not providers:
            raise ValueError("the gateway needs at least one provider")
        self._providers = list(providers)
        self._limits = limits
        self._sleep = sleep
        self.ledger = ledger or UsageLedger(limits.case_token_budget)

    @property
    def provider_names(self) -> tuple[str, ...]:
        """Names of the configured providers, primary first."""
        return tuple(p.name for p in self._providers)

    @property
    def limits(self) -> LlmLimits:
        """The reliability and budget limits in force."""
        return self._limits

    # --- plain completion -----------------------------------------------
    def complete(self, request: LlmRequest, *, case_id: str | None = None) -> LlmResponse:
        """Return a response from the first provider that succeeds."""
        self.ledger.check_budget(case_id, request.max_tokens)
        failures: list[str] = []
        for provider in self._providers:
            outcome = self._try_provider(provider, request, failures)
            if outcome is not None:
                self.ledger.record(case_id, outcome)
                return outcome
        raise AllProvidersFailedError("; ".join(failures))

    def _try_provider(
        self, provider: LlmProvider, request: LlmRequest, failures: list[str]
    ) -> LlmResponse | None:
        for attempt in range(1, self._limits.max_attempts_per_provider + 1):
            try:
                return provider.complete(request)
            except TransientLlmError as error:
                failures.append(f"{provider.name} attempt {attempt}: {_plain(provider, error)}")
                if attempt < self._limits.max_attempts_per_provider:
                    self._sleep(self._delay(attempt, error.retry_after))
            except (LlmAuthError, LlmRequestError) as error:
                failures.append(f"{provider.name}: {_plain(provider, error)}")
                break  # retrying the same provider cannot help; try the next one
        log.warning("provider %s failed; trying the next one", provider.name)
        return None

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        backoff = self._limits.backoff_seconds * (1 << (attempt - 1))
        wait = max(backoff, retry_after or 0.0)
        return min(wait, self._limits.max_backoff_seconds)

    # --- structured output ------------------------------------------------
    def structured(
        self,
        request: LlmRequest,
        schema: type[T],
        *,
        case_id: str | None = None,
    ) -> StructuredResult[T]:
        """Return an instance of ``schema`` built from the model's JSON answer.

        On invalid output the model is shown the error and asked again, up to
        ``limits.max_repairs`` times.
        """
        schema_json = schema.model_json_schema()
        instruction = ChatMessage(
            role=Role.SYSTEM,
            content=(
                "Reply with exactly one JSON object that conforms to this JSON Schema. "
                "Output JSON only: no explanation and no markdown code fences.\n"
                f"Schema: {json.dumps(schema_json, separators=(',', ':'))}"
            ),
        )
        messages = (instruction, *request.messages)
        prompt_total = completion_total = 0
        last_error = "no attempt made"
        for repairs in range(self._limits.max_repairs + 1):
            attempt = request.model_copy(
                update={"messages": messages, "json_output": True, "json_schema": schema_json}
            )
            response = self.complete(attempt, case_id=case_id)
            prompt_total += response.usage.prompt_tokens
            completion_total += response.usage.completion_tokens
            try:
                value = schema.model_validate(_extract_json(response.text))
            except (ValueError, ValidationError) as error:
                last_error = _summarize(error)
                messages = (
                    *messages,
                    ChatMessage(role=Role.ASSISTANT, content=response.text),
                    ChatMessage(
                        role=Role.USER,
                        content=f"That reply was not valid: {last_error}\nReturn corrected JSON.",
                    ),
                )
                continue
            usage = TokenUsage(prompt_tokens=prompt_total, completion_tokens=completion_total)
            return StructuredResult(value, response, repairs, usage)
        attempts = self._limits.max_repairs + 1
        raise StructuredOutputError(
            f"no valid {schema.__name__} after {attempts} attempts: {last_error}"
        )


def _plain(provider: LlmProvider, error: Exception) -> str:
    """Return the error text without a leading ``<provider>: `` (the caller adds its own)."""
    return str(error).removeprefix(f"{provider.name}: ")


def _extract_json(text: str) -> object:
    """Parse JSON from ``text``, tolerating markdown fences and a little surrounding prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("the reply did not contain a JSON object") from None
        return json.loads(cleaned[start : end + 1])


def _summarize(error: Exception) -> str:
    """Describe a parse or validation failure compactly, for the model and for logs."""
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in error.errors()[:5]
        ]
        return "schema errors: " + "; ".join(parts)
    return f"not valid JSON ({error})"[:300]


__all__ = ["LlmError", "LlmGateway", "StructuredResult"]
