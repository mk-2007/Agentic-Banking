"""A scripted provider for tests and offline demos: no network, fully deterministic."""

from collections.abc import Callable, Sequence

from .errors import LlmError
from .messages import LlmRequest, LlmResponse, TokenUsage

Script = Sequence[str | LlmError] | Callable[[LlmRequest], str]


class ScriptedProvider:
    """Returns pre-written answers (or raises pre-written errors) in order.

    ``script`` is either a sequence consumed one item per call (a string is returned, an
    `LlmError` is raised), or a function of the request. Every request is recorded.
    """

    def __init__(
        self, script: Script, *, name: str = "scripted", model: str = "scripted-1"
    ) -> None:
        self._script = script
        self._name = name
        self._model = model
        self._index = 0
        self.requests: list[LlmRequest] = []

    @property
    def name(self) -> str:
        """Provider name."""
        return self._name

    @property
    def model(self) -> str:
        """Model id."""
        return self._model

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return or raise the next scripted outcome."""
        self.requests.append(request)
        if callable(self._script):
            text = self._script(request)
        else:
            if self._index >= len(self._script):
                raise AssertionError("scripted provider ran out of responses")
            item = self._script[self._index]
            self._index += 1
            if isinstance(item, LlmError):
                raise item
            text = item
        prompt_tokens = sum(len(m.content) for m in request.messages) // 4
        return LlmResponse(
            text=text,
            usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=max(1, len(text) // 4)),
            provider=self._name,
            model=self._model,
            latency_ms=1,
            finish_reason="stop",
        )

    @property
    def calls(self) -> int:
        """Number of requests received."""
        return len(self.requests)
