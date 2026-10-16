"""How hard the graph may try before it gives up (loop limits and retries, Phase 6c).

Every loop in the graph is bounded by a number here, so no case can spin forever or wait on humans
without an end. Only tool failures that are plausibly temporary are retried; a refused call
(denied, out of scope, invalid arguments) is a rule talking and is never retried.
"""

from dataclasses import dataclass
from typing import Final

# Tool error codes worth another attempt. Everything else fails the case at once.
TRANSIENT_TOOL_CODES: Final[frozenset[str]] = frozenset({"timeout", "internal_error"})


@dataclass(frozen=True)
class RunLimits:
    """The bounds on one case run."""

    max_attempts: int = 2  # tries per agent step, counting the first
    max_vote_rounds: int = 5  # times a case may pause for votes that leave it still pending

    def __post_init__(self) -> None:
        """Reject limits that would stop a case from ever trying."""
        if self.max_attempts < 1 or self.max_vote_rounds < 1:
            raise ValueError("limits must be at least 1")
