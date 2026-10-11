"""Time as an injectable dependency.

Code that needs "now" receives a `Clock` instead of calling ``datetime.now`` itself, so tests
can freeze time and approval expiry can be tested exactly. `utc_now` is the only impure function.
"""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current time in UTC (timezone-aware)."""
    return datetime.now(UTC)
