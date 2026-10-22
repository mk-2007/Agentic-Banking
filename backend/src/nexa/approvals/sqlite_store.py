"""A durable approval store on SQLite, with the same behaviour as `InMemoryApprovalStore`.

Why: approvals and the single-use rule must survive a restart, or an approval could be spent twice
across runs. Consumption is one conditional UPDATE, so it is atomic even across processes.

shortcut: one local SQLite file (WAL); move to a server database when several hosts share it.
"""

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path

from nexa.domain.approval import ApprovalRequest, ApprovalVote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, body TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS votes (
  approval_id TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL,
  PRIMARY KEY (approval_id, seq));
"""


class SqliteApprovalStore:
    """Thread-safe store of approval requests and votes. Nothing is ever deleted."""

    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def add_request(self, request: ApprovalRequest) -> None:
        """Store a new request. The same id cannot be stored twice."""
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO approvals (id, body) VALUES (?, ?)",
                    (request.id, request.model_dump_json()),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"approval {request.id} already exists") from None

    def set_votes(self, approval_id: str, votes: Sequence[ApprovalVote]) -> None:
        """Replace the recorded votes with the full set received so far."""
        with self._lock:
            if (
                self._db.execute("SELECT 1 FROM approvals WHERE id=?", (approval_id,)).fetchone()
                is None
            ):
                raise KeyError(approval_id)
            self._db.execute("BEGIN")
            self._db.execute("DELETE FROM votes WHERE approval_id=?", (approval_id,))
            self._db.executemany(
                "INSERT INTO votes VALUES (?, ?, ?)",
                [(approval_id, i, v.model_dump_json()) for i, v in enumerate(votes)],
            )
            self._db.execute("COMMIT")

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Return the approval request, or None if it does not exist."""
        with self._lock:
            row = self._db.execute(
                "SELECT body FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
        return ApprovalRequest.model_validate_json(row[0]) if row else None

    def get_votes(self, approval_id: str) -> Sequence[ApprovalVote]:
        """Return every vote cast on the request."""
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM votes WHERE approval_id=? ORDER BY seq", (approval_id,)
            ).fetchall()
        return tuple(ApprovalVote.model_validate_json(r[0]) for r in rows)

    def try_consume(self, approval_id: str) -> bool:
        """Mark the approval used. Return False if it is unknown or was already used."""
        with self._lock:
            done = self._db.execute(
                "UPDATE approvals SET used=1 WHERE id=? AND used=0", (approval_id,)
            )
            return done.rowcount == 1
