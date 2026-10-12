"""Token and cost accounting, with a per-case budget (PRD sections 38-39: bounded loops, cost)."""

import threading
from collections import defaultdict
from dataclasses import dataclass

from nexa.config.llm import MODEL_PRICES_USD_PER_MILLION

from .errors import BudgetExceededError
from .messages import LlmResponse


@dataclass(frozen=True)
class UsageSummary:
    """Totals for one case, or for everything."""

    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        """Prompt plus completion tokens."""
        return self.prompt_tokens + self.completion_tokens


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return the cost of a call; models without a listed price count as free tier."""
    price_in, price_out = MODEL_PRICES_USD_PER_MILLION.get(model, (0.0, 0.0))
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


class UsageLedger:
    """Thread-safe record of model usage per case, enforcing a token budget."""

    def __init__(self, case_token_budget: int) -> None:
        self._budget = case_token_budget
        self._lock = threading.Lock()
        self._rows: dict[str, list[LlmResponse]] = defaultdict(list)

    def check_budget(self, case_id: str | None, requested_tokens: int) -> None:
        """Raise `BudgetExceededError` if the case could not afford ``requested_tokens`` more."""
        if case_id is None:
            return
        used = self.summary(case_id).total_tokens
        if used + requested_tokens > self._budget:
            raise BudgetExceededError(
                f"case {case_id} would exceed its {self._budget}-token budget "
                f"({used} used, {requested_tokens} requested)"
            )

    def record(self, case_id: str | None, response: LlmResponse) -> None:
        """Add a finished call to the case's usage."""
        with self._lock:
            self._rows[case_id or "_unassigned"].append(response)

    def summary(self, case_id: str | None = None) -> UsageSummary:
        """Return totals for ``case_id``, or for all cases if None."""
        with self._lock:
            rows = (
                self._rows.get(case_id, [])
                if case_id is not None
                else [r for rs in self._rows.values() for r in rs]
            )
        prompt = sum(r.usage.prompt_tokens for r in rows)
        completion = sum(r.usage.completion_tokens for r in rows)
        cost = sum(
            cost_usd(r.model, r.usage.prompt_tokens, r.usage.completion_tokens) for r in rows
        )
        return UsageSummary(len(rows), prompt, completion, cost)
