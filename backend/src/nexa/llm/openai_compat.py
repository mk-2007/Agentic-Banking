"""A provider for any OpenAI-compatible chat completions endpoint (Groq, Gemini, and others).

The adapter does four things carefully: it builds the request, maps HTTP and network failures to
the gateway's error types (retryable or not), never lets the API key appear in an error message, and
degrades gracefully if a model rejects ``response_format``.
"""

import time
from typing import Any

import httpx

from nexa.config.llm import JsonMode

from .errors import LlmAuthError, LlmRequestError, TransientLlmError
from .messages import LlmRequest, LlmResponse, TokenUsage

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_MAX_ERROR_CHARS = 300


class OpenAiCompatibleProvider:
    """Calls ``{base_url}/chat/completions`` with a bearer token."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        json_mode: JsonMode = JsonMode.JSON_OBJECT,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"no API key configured for provider {name}")
        self._name = name
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._model = model
        self._json_mode = json_mode
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @property
    def name(self) -> str:
        """Short provider name used in logs and usage records."""
        return self._name

    @property
    def model(self) -> str:
        """The model id requests are sent to."""
        return self._model

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Send ``request`` and return the model's answer."""
        started = time.monotonic()
        response = self._post(self._body(request, use_json_mode=True))
        if response.status_code == 400 and self._rejects_response_format(response, request):
            self._json_mode = JsonMode.NONE  # remember: this model cannot do it
            response = self._post(self._body(request, use_json_mode=False))
        data = self._check(response)
        return self._parse(data, int((time.monotonic() - started) * 1000))

    # --- request ------------------------------------------------------
    def _body(self, request: LlmRequest, *, use_json_mode: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_output and use_json_mode:
            if self._json_mode is JsonMode.JSON_OBJECT:
                body["response_format"] = {"type": "json_object"}
            elif self._json_mode is JsonMode.JSON_SCHEMA and request.json_schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": request.json_schema},
                }
        return body

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException:
            raise TransientLlmError(f"{self._name}: request timed out") from None
        except httpx.TransportError as error:
            raise TransientLlmError(
                f"{self._name}: network error ({type(error).__name__})"
            ) from None

    # --- response -----------------------------------------------------
    def _check(self, response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if 200 <= status < 300:
            try:
                data: dict[str, Any] = response.json()
            except ValueError:
                raise TransientLlmError(f"{self._name}: response was not valid JSON") from None
            return data
        detail = self._redact(self._error_message(response))
        if status in (401, 403):
            raise LlmAuthError(f"{self._name}: API key rejected (HTTP {status})")
        if status in _RETRYABLE_STATUS or status >= 500:
            raise TransientLlmError(
                f"{self._name}: HTTP {status} {detail}", retry_after=self._retry_after(response)
            )
        if status == 404:
            raise LlmRequestError(
                f"{self._name}: model or endpoint not found ({self._model}). "
                "Run scripts/llm_smoke_test.py --list-models, then set the model variable.",
                status,
            )
        raise LlmRequestError(f"{self._name}: HTTP {status} {detail}", status)

    def _parse(self, data: dict[str, Any], latency_ms: int) -> LlmResponse:
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            finish = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise TransientLlmError(f"{self._name}: unexpected response shape") from None
        if not text.strip():
            hint = (
                " (hit the token limit; the model may be using its budget to think)"
                if finish == "length"
                else ""
            )
            raise TransientLlmError(f"{self._name}: empty answer{hint}")
        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or max(1, len(text) // 4))
        return LlmResponse(
            text=text,
            usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
            provider=self._name,
            model=self._model,
            latency_ms=latency_ms,
            finish_reason=finish,
        )

    # --- helpers --------------------------------------------------------
    def _rejects_response_format(self, response: httpx.Response, request: LlmRequest) -> bool:
        sent = request.json_output and self._json_mode is not JsonMode.NONE
        return sent and "response_format" in response.text.lower()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("retry-after")
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            error = response.json().get("error", {})
            text = error.get("message", "") if isinstance(error, dict) else str(error)
        except (ValueError, AttributeError):
            text = response.text
        return text[:_MAX_ERROR_CHARS]

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***")
