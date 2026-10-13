"""Validated structured output: fences, repairs, extra fields, and giving up cleanly."""

from typing import Literal

import pytest

from nexa.domain.base import Contract
from nexa.llm import (
    ChatMessage,
    LlmGateway,
    LlmRequest,
    Role,
    ScriptedProvider,
    StructuredOutputError,
)


class Verdict(Contract):
    label: Literal["ok", "suspicious"]
    reason: str


def ask() -> LlmRequest:
    return LlmRequest(messages=(ChatMessage(role=Role.USER, content="classify this payment"),))


def run(script: list[str], **kwargs: object) -> tuple[ScriptedProvider, object]:
    provider = ScriptedProvider(script)  # type: ignore[arg-type]
    gateway = LlmGateway([provider], sleep=lambda s: None)
    try:
        return provider, gateway.structured(ask(), Verdict, **kwargs)  # type: ignore[arg-type]
    except StructuredOutputError as error:
        return provider, error


GOOD = '{"label": "ok", "reason": "routine purchase"}'


def test_valid_json_is_returned_as_a_validated_object() -> None:
    provider, result = run([GOOD])
    assert result.value == Verdict(label="ok", reason="routine purchase")  # type: ignore[attr-defined]
    assert result.repairs == 0 and provider.calls == 1  # type: ignore[attr-defined]


def test_the_request_carries_the_schema_and_asks_for_json() -> None:
    provider, _ = run([GOOD])
    sent = provider.requests[0]
    assert sent.json_output is True and sent.json_schema is not None
    first = sent.messages[0]
    assert (
        first.role is Role.SYSTEM
        and "JSON Schema" in first.content
        and "suspicious" in first.content
    )
    assert sent.messages[-1].content == "classify this payment"


@pytest.mark.parametrize(
    "text",
    [f"```json\n{GOOD}\n```", f"```\n{GOOD}\n```", f"Sure! Here you go:\n{GOOD}\nHope that helps."],
)
def test_fences_and_chatter_around_the_json_are_tolerated(text: str) -> None:
    _, result = run([text])
    assert result.value.label == "ok" and result.repairs == 0  # type: ignore[attr-defined]


def test_invalid_output_is_repaired_by_showing_the_model_the_error() -> None:
    provider, result = run(['{"label": "maybe", "reason": "?"}', GOOD])
    assert result.repairs == 1 and result.value.label == "ok"  # type: ignore[attr-defined]
    retry = provider.requests[1].messages
    assert retry[-2].role is Role.ASSISTANT and "maybe" in retry[-2].content
    assert retry[-1].role is Role.USER and "label" in retry[-1].content  # names the bad field


def test_extra_fields_are_rejected_and_repaired() -> None:
    _, result = run(['{"label": "ok", "reason": "x", "approved": true}', GOOD])
    assert result.repairs == 1  # type: ignore[attr-defined]


def test_prose_instead_of_json_is_repaired() -> None:
    _, result = run(["I think it looks fine.", GOOD])
    assert result.repairs == 1  # type: ignore[attr-defined]


def test_giving_up_raises_a_clear_error_after_the_repair_limit() -> None:
    provider, error = run(["nope"] * 3)
    assert isinstance(error, StructuredOutputError)
    assert "Verdict" in str(error) and "3 attempts" in str(error)
    assert provider.calls == 3  # initial attempt plus two repairs


def test_usage_is_summed_across_repairs() -> None:
    provider, result = run(["bad", GOOD])
    total = sum(len(m.content) for m in provider.requests[0].messages) // 4
    assert result.usage.prompt_tokens > total  # type: ignore[attr-defined]
    assert result.usage.completion_tokens >= 2  # type: ignore[attr-defined]


def test_structured_calls_count_against_the_case_budget() -> None:
    provider = ScriptedProvider(["bad"] * 3)
    gateway = LlmGateway([provider], sleep=lambda s: None)
    with pytest.raises(Exception):  # noqa: B017, PT011 - budget or structured error, either stops it
        gateway.structured(ask().model_copy(update={"max_tokens": 2048}), Verdict, case_id="c")
    assert gateway.ledger.summary("c").calls >= 1
