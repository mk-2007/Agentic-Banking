"""Append-only audit logs backed by the domain hash chain.

`InMemoryAuditLog` is used in tests and the demo. `JsonlAuditLog` also persists one JSON
line per event and re-verifies the whole chain when it is opened, so tampering with the file
between runs is detected instead of silently trusted.
"""

import os
import threading
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from nexa.domain.audit import GENESIS_HASH, AuditDraft, AuditEvent, first_broken_link, seal
from nexa.domain.errors import DomainError


class AuditTamperedError(DomainError):
    """Raised when a stored audit log fails verification."""


class AuditLog(Protocol):
    """What the rest of the platform may do with the audit log."""

    def append(self, draft: AuditDraft) -> AuditEvent:
        """Chain ``draft`` onto the log and return the stored event."""
        ...

    def events(self) -> tuple[AuditEvent, ...]:
        """Return every event, oldest first."""
        ...

    def verify(self) -> int | None:
        """Return the index of the first broken link, or None if the chain is intact."""
        ...


class InMemoryAuditLog:
    """Thread-safe, append-only log held in memory. There is no update or delete."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, draft: AuditDraft) -> AuditEvent:
        """Chain ``draft`` onto the log and return the stored event."""
        with self._lock:
            prev = self._events[-1].event_hash if self._events else GENESIS_HASH
            event = seal(draft, prev)
            self._persist(event)
            self._events.append(event)
            return event

    def events(self) -> tuple[AuditEvent, ...]:
        """Return every event, oldest first."""
        with self._lock:
            return tuple(self._events)

    def for_case(self, case_id: str) -> tuple[AuditEvent, ...]:
        """Return the events that belong to ``case_id``."""
        return tuple(e for e in self.events() if e.case_id == case_id)

    def verify(self) -> int | None:
        """Return the index of the first broken link, or None if the chain is intact."""
        return first_broken_link(self.events())

    def _persist(self, event: AuditEvent) -> None:
        """Store ``event`` elsewhere; subclasses override this (runs before the event is kept)."""


class JsonlAuditLog(InMemoryAuditLog):
    """In-memory log that also appends each event to a JSON-lines file."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        if path.exists():
            self._load()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        loaded: list[AuditEvent] = []
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                loaded.append(AuditEvent.model_validate_json(line))
            except ValidationError as error:
                raise AuditTamperedError(f"line {number} is corrupt or edited: {error}") from None
        broken = first_broken_link(loaded)
        if broken is not None:
            raise AuditTamperedError(f"hash chain is broken at event {broken}")
        self._events = loaded

    def _persist(self, event: AuditEvent) -> None:
        with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
