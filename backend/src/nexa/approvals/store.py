"""An in-memory approval store: the requests, the votes cast on them, and single-use consumption.

It implements `security.ApprovalSource`, so the guarded execution tool can check an approval
against it. Orchestration writes the request and the votes; only the execution tool consumes one.
Consumption is atomic and permanent: an approval id can be used once, ever.
"""

import threading
from collections.abc import Sequence
from typing import Protocol

from nexa.domain.approval import ApprovalRequest, ApprovalVote


class ApprovalStore(Protocol):
    """What orchestration and the execution tool need from an approval store."""

    def add_request(self, request: ApprovalRequest) -> None:
        """Store a new request."""
        ...

    def set_votes(self, approval_id: str, votes: Sequence[ApprovalVote]) -> None:
        """Replace the recorded votes."""
        ...

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Return the request or None."""
        ...

    def get_votes(self, approval_id: str) -> Sequence[ApprovalVote]:
        """Return the votes."""
        ...

    def try_consume(self, approval_id: str) -> bool:
        """Mark used, once."""
        ...


class InMemoryApprovalStore:
    """Thread-safe store of approval requests and votes. Nothing is ever deleted."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._votes: dict[str, list[ApprovalVote]] = {}
        self._used: set[str] = set()
        self._lock = threading.Lock()

    def add_request(self, request: ApprovalRequest) -> None:
        """Store a new request. The same id cannot be stored twice."""
        with self._lock:
            if request.id in self._requests:
                raise ValueError(f"approval {request.id} already exists")
            self._requests[request.id] = request
            self._votes[request.id] = []

    def set_votes(self, approval_id: str, votes: Sequence[ApprovalVote]) -> None:
        """Replace the recorded votes with the full set received so far."""
        with self._lock:
            if approval_id not in self._requests:
                raise KeyError(approval_id)
            self._votes[approval_id] = list(votes)

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Return the approval request, or None if it does not exist."""
        with self._lock:
            return self._requests.get(approval_id)

    def get_votes(self, approval_id: str) -> Sequence[ApprovalVote]:
        """Return every vote cast on the request."""
        with self._lock:
            return tuple(self._votes.get(approval_id, ()))

    def try_consume(self, approval_id: str) -> bool:
        """Mark the approval used. Return False if it is unknown or was already used."""
        with self._lock:
            if approval_id not in self._requests or approval_id in self._used:
                return False
            self._used.add(approval_id)
            return True
