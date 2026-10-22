"""Username and password sign-in with short-lived server-side sessions.

Why: pasting a bearer token into a page is not how people sign in to a bank. Here a user proves a
password (stored only as a salted scrypt hash), gets a random session id in an HttpOnly cookie, and
the session expires. A user is locked out for a while after repeated failures. The role still comes
from the user record and is checked by plain code, exactly as for bearer tokens.

shortcut: sessions and lockouts live in memory and there is no second factor; move them to the
durable store (WP4) and put an OIDC provider with MFA behind ``Accounts.login`` for production.
"""

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from nexa.api.principals import ALLOWED_ROLES, Principal
from nexa.domain.actors import Role

SESSION_SECONDS = 8 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return ``scrypt$<salt hex>$<hash hex>`` for ``password``."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check ``password`` against a ``hash_password`` value in constant time."""
    try:
        _, salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


def parse_users(spec: str) -> dict[str, tuple[str, Principal]]:
    """Parse ``user:hash:role[:customer_id]`` entries separated by commas."""
    found: dict[str, tuple[str, Principal]] = {}
    for entry in filter(None, (part.strip() for part in spec.split(","))):
        pieces = entry.split(":")
        if len(pieces) not in (3, 4) or not all(pieces):
            raise ValueError("each user entry must look like user:hash:role[:customer_id]")
        user, stored, role_name, *linked = pieces
        try:
            role = Role(role_name)
        except ValueError:
            raise ValueError(f"unknown role {role_name!r}") from None
        if role not in ALLOWED_ROLES or (linked and role is not Role.CUSTOMER) or user in found:
            raise ValueError(f"invalid or repeated user {user!r}")
        found[user] = (stored, Principal(user, role, linked[0] if linked else None))
    return found


@dataclass
class Accounts:
    """Users, their live sessions and the failed-login counters."""

    users: dict[str, tuple[str, Principal]]
    clock: Callable[[], float] = time.monotonic
    _sessions: dict[str, tuple[Principal, float]] = field(default_factory=dict)
    _failures: dict[str, tuple[int, float]] = field(default_factory=dict)

    def login(self, username: str, password: str) -> str | None:
        """Return a new session id, or None for a wrong password or a locked-out user."""
        now = self.clock()
        count, since = self._failures.get(username, (0, now))
        if count >= MAX_FAILURES and now - since < LOCKOUT_SECONDS:
            return None
        known = self.users.get(username)
        # always hash, so an unknown user costs the same time as a wrong password
        ok = verify_password(password, known[0] if known else hash_password("x"))
        if known is None or not ok:
            self._failures[username] = (count + 1 if now - since < LOCKOUT_SECONDS else 1, since)
            return None
        self._failures.pop(username, None)
        session = secrets.token_urlsafe(32)
        self._sessions[session] = (known[1], now + SESSION_SECONDS)
        return session

    def principal(self, session: str | None) -> Principal | None:
        """Return the signed-in user for ``session``, or None if unknown or expired."""
        found = self._sessions.get(session or "")
        if found is None:
            return None
        if found[1] <= self.clock():
            self._sessions.pop(session or "", None)
            return None
        return found[0]

    def logout(self, session: str | None) -> None:
        """End ``session``."""
        self._sessions.pop(session or "", None)
