"""The OpenAI-compatible adapter, exercised against a fake HTTP server (no network)."""

import json
from collections.abc import Callable

import httpx
import pytest

from nexa.config.llm import JsonMode
from nexa.llm import (
    ChatMessage,
    LlmAuthError,
    LlmRequest,
    LlmRequestError,
    Role,
    TransientLlmError,
)
from nexa.llm.openai_compat import OpenAiCompatibleProvider

KEY = "sk-super-secret-key"
OK = {
    "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
}


def provider(
    handler: Callable[[httpx.Request], httpx.Response],
    json_mode: JsonMode = JsonMode.JSON_OBJECT,
) -> OpenAiCompatibleProvider:
    return OpenAiCompatibleProvider(
        name="test", base_url="https://api.test/v1/", api_key=KEY, model="m-1",
        json_mode=json_mode, client=httpx.Client(transport=httpx.MockTransport(handler)),
    )  # fmt: skip


def ask(json_output: bool = False, schema: dict[str, object] | None = None) -> LlmRequest:
    return LlmRequest(
        messages=(ChatMessage(role=Role.USER, content="hi"),),
        json_output=json_output,
        json_schema=schema,
    )


def test_request_shape_and_response_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=OK)

    response = provider(handler).complete(ask())
    (request,) = seen
    assert str(request.url) == "https://api.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "m-1" and body["temperature"] == 0.0 and body["max_tokens"] == 2048
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "response_format" not in body
    assert response.text == "hello" and response.usage.total == 14
    assert response.provider == "test" and response.model == "m-1"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (JsonMode.JSON_OBJECT, {"type": "json_object"}),
        (
            JsonMode.JSON_SCHEMA,
            {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": {"type": "object"}},
            },
        ),
        (JsonMode.NONE, None),
    ],
)
def test_json_modes(mode: JsonMode, expected: object) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=OK)

    provider(handler, mode).complete(ask(json_output=True, schema={"type": "object"}))
    assert seen[0].get("response_format") == expected


def test_a_model_that_rejects_response_format_is_retried_without_it() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(
                400, json={"error": {"message": "response_format is not supported"}}
            )
        return httpx.Response(200, json=OK)

    p = provider(handler)
    assert p.complete(ask(json_output=True)).text == "hello"
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]
    p.complete(ask(json_output=True))  # remembered: no further wasted attempt
    assert len(bodies) == 3 and "response_format" not in bodies[2]


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_keys_are_auth_errors_that_never_echo_the_key(status: int) -> None:
    handler = lambda r: httpx.Response(status, json={"error": {"message": f"bad key {KEY}"}})  # noqa: E731
    with pytest.raises(LlmAuthError) as caught:
        provider(handler).complete(ask())
    assert KEY not in str(caught.value) and str(status) in str(caught.value)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_retryable_statuses_are_transient(status: int) -> None:
    handler = lambda r: httpx.Response(status, json={"error": {"message": "slow down"}})  # noqa: E731
    with pytest.raises(TransientLlmError):
        provider(handler).complete(ask())


def test_retry_after_header_is_parsed() -> None:
    handler = lambda r: httpx.Response(429, headers={"retry-after": "7"}, json={})  # noqa: E731
    with pytest.raises(TransientLlmError) as caught:
        provider(handler).complete(ask())
    assert caught.value.retry_after == 7.0


def test_unknown_model_gives_actionable_advice() -> None:
    handler = lambda r: httpx.Response(404, json={"error": {"message": "no such model"}})  # noqa: E731
    with pytest.raises(LlmRequestError, match="--list-models") as caught:
        provider(handler).complete(ask())
    assert caught.value.status == 404


def test_bad_requests_are_not_retryable_and_redact_the_key() -> None:
    handler = lambda r: httpx.Response(400, json={"error": {"message": f"invalid {KEY}"}})  # noqa: E731
    with pytest.raises(LlmRequestError) as caught:
        provider(handler).complete(ask())
    assert KEY not in str(caught.value) and "***" in str(caught.value)


def test_server_error_messages_are_redacted_too() -> None:
    handler = lambda r: httpx.Response(500, json={"error": {"message": f"oops {KEY}"}})  # noqa: E731
    with pytest.raises(TransientLlmError) as caught:
        provider(handler).complete(ask())
    assert KEY not in str(caught.value)


def test_network_failures_are_transient() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler in (timeout, refused):
        with pytest.raises(TransientLlmError):
            provider(handler).complete(ask())


def test_empty_answers_are_transient_with_a_token_limit_hint() -> None:
    body = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {}}
    with pytest.raises(TransientLlmError, match="token limit"):
        provider(lambda r: httpx.Response(200, json=body)).complete(ask())


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": None}]}])
def test_unexpected_shapes_are_transient(body: dict[str, object]) -> None:
    with pytest.raises(TransientLlmError):
        provider(lambda r: httpx.Response(200, json=body)).complete(ask())


def test_non_json_success_body_is_transient() -> None:
    with pytest.raises(TransientLlmError):
        provider(lambda r: httpx.Response(200, text="<html>gateway</html>")).complete(ask())


def test_missing_usage_is_estimated() -> None:
    body = {"choices": [{"message": {"content": "x" * 40}, "finish_reason": "stop"}]}
    response = provider(lambda r: httpx.Response(200, json=body)).complete(ask())
    assert response.usage.completion_tokens == 10


def test_a_provider_without_a_key_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="no API key"):
        OpenAiCompatibleProvider(name="x", base_url="https://a", api_key="", model="m")


def test_not_found_includes_the_providers_own_explanation() -> None:
    handler = lambda r: httpx.Response(404, json={"error": {"message": "model is retired"}})  # noqa: E731
    with pytest.raises(LlmRequestError) as caught:
        provider(handler).complete(ask())
    assert "model is retired" in str(caught.value) and "m-1" in str(caught.value)
