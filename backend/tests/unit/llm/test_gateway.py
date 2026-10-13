"""Retries, failover and budgets in the gateway, using scripted providers and a fake clock."""

import pytest

from nexa.config.llm import LlmLimits
from nexa.llm import (
    AllProvidersFailedError,
    BudgetExceededError,
    ChatMessage,
    LlmAuthError,
    LlmGateway,
    LlmRequest,
    LlmRequestError,
    Role,
    ScriptedProvider,
    TransientLlmError,
)


def req(max_tokens: int = 256) -> LlmRequest:
    return LlmRequest(
        messages=(ChatMessage(role=Role.USER, content="hello there"),), max_tokens=max_tokens
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def gateway(
    *providers: ScriptedProvider, sleeps: Sleeps | None = None, **limits: object
) -> LlmGateway:
    return LlmGateway(list(providers), limits=LlmLimits(**limits), sleep=sleeps or Sleeps())  # type: ignore[arg-type]


def test_the_first_provider_answers_and_usage_is_recorded() -> None:
    primary = ScriptedProvider(["fine"], name="groq")
    gw = gateway(primary)
    response = gw.complete(req(), case_id="case_1")
    assert response.text == "fine" and primary.calls == 1
    summary = gw.ledger.summary("case_1")
    assert summary.calls == 1 and summary.total_tokens == response.usage.total


def test_transient_errors_are_retried_with_exponential_backoff() -> None:
    sleeps = Sleeps()
    p = ScriptedProvider([TransientLlmError("429"), TransientLlmError("429"), "ok"])
    assert gateway(p, sleeps=sleeps, backoff_seconds=1.0).complete(req()).text == "ok"
    assert p.calls == 3 and sleeps.calls == [1.0, 2.0]


def test_retry_after_is_respected_but_capped() -> None:
    sleeps = Sleeps()
    p = ScriptedProvider(
        [
            TransientLlmError("slow", retry_after=5.0),
            TransientLlmError("slow", retry_after=999.0),
            "ok",
        ]
    )
    gateway(p, sleeps=sleeps, backoff_seconds=1.0, max_backoff_seconds=20.0).complete(req())
    assert sleeps.calls == [5.0, 20.0]


def test_exhausted_retries_fail_over_to_the_next_provider() -> None:
    primary = ScriptedProvider([TransientLlmError("down")] * 3, name="groq")
    backup = ScriptedProvider(["from backup"], name="gemini")
    response = gateway(primary, backup).complete(req())
    assert response.text == "from backup" and response.provider == "gemini"
    assert primary.calls == 3 and backup.calls == 1


@pytest.mark.parametrize("error", [LlmAuthError("bad key"), LlmRequestError("bad model", 404)])
def test_non_retryable_errors_skip_straight_to_the_next_provider(error: Exception) -> None:
    primary = ScriptedProvider([error], name="groq")  # type: ignore[list-item]
    backup = ScriptedProvider(["ok"], name="gemini")
    sleeps = Sleeps()
    assert gateway(primary, backup, sleeps=sleeps).complete(req()).text == "ok"
    assert primary.calls == 1 and sleeps.calls == []


def test_when_everyone_fails_the_error_names_each_provider() -> None:
    a = ScriptedProvider([TransientLlmError("a down")] * 3, name="groq")
    b = ScriptedProvider([LlmAuthError("b key rejected")], name="gemini")
    with pytest.raises(AllProvidersFailedError) as caught:
        gateway(a, b).complete(req())
    message = str(caught.value)
    assert "groq" in message and "gemini" in message and "a down" in message


def test_the_case_budget_is_enforced_before_calling_the_model() -> None:
    p = ScriptedProvider(lambda r: "x" * 400)
    gw = gateway(p, case_token_budget=1_000)
    gw.complete(req(max_tokens=400), case_id="case_1")
    gw.complete(req(max_tokens=400), case_id="case_1")
    calls_before = p.calls
    with pytest.raises(BudgetExceededError, match="case_1"):
        gw.complete(req(max_tokens=900), case_id="case_1")
    assert p.calls == calls_before  # refused without spending anything


def test_budgets_are_per_case() -> None:
    gw = gateway(ScriptedProvider(lambda r: "ok"), case_token_budget=1_000)
    gw.complete(req(max_tokens=900), case_id="case_a")
    gw.complete(req(max_tokens=900), case_id="case_b")  # a different case has its own budget


def test_calls_without_a_case_are_not_budgeted() -> None:
    gw = gateway(ScriptedProvider(lambda r: "ok"), case_token_budget=1_000)
    gw.complete(req(max_tokens=30_000))


def test_a_gateway_needs_providers() -> None:
    with pytest.raises(ValueError, match="at least one"):
        LlmGateway([])


def test_provider_names_are_listed_primary_first() -> None:
    gw = gateway(ScriptedProvider(["x"], name="groq"), ScriptedProvider(["y"], name="gemini"))
    assert gw.provider_names == ("groq", "gemini")


def test_failover_summaries_do_not_repeat_the_provider_name() -> None:
    a = ScriptedProvider([LlmRequestError("groq: model gone", 404)], name="groq")
    b = ScriptedProvider([LlmAuthError("gemini: key rejected")], name="gemini")
    with pytest.raises(AllProvidersFailedError) as caught:
        gateway(a, b).complete(req())
    assert "groq: groq:" not in str(caught.value) and "gemini: gemini:" not in str(caught.value)
    assert "groq: model gone" in str(caught.value) and "gemini: key rejected" in str(caught.value)
