"""Sign-in: password hashing, sessions, expiry and lockout."""

from nexa.api.principals import Principal
from nexa.api.sessions import (
    LOCKOUT_SECONDS,
    MAX_FAILURES,
    SESSION_SECONDS,
    Accounts,
    hash_password,
    parse_users,
    verify_password,
)
from nexa.domain.actors import Role


def make(now: list[float]) -> Accounts:
    users = {"ana": (hash_password("secret"), Principal("ana", Role.FRAUD_ANALYST))}
    return Accounts(users, clock=lambda: now[0])


def test_password_hash_roundtrip() -> None:
    stored = hash_password("secret")
    assert verify_password("secret", stored)
    assert not verify_password("Secret", stored)
    assert not verify_password("secret", "garbage")


def test_login_gives_a_session_with_the_users_role() -> None:
    accounts = make([0.0])
    session = accounts.login("ana", "secret")
    assert session and accounts.principal(session) == Principal("ana", Role.FRAUD_ANALYST)
    assert accounts.login("ana", "wrong") is None and accounts.login("nobody", "x") is None


def test_session_expires_and_logout_ends_it() -> None:
    now = [0.0]
    accounts = make(now)
    session = accounts.login("ana", "secret")
    now[0] = SESSION_SECONDS + 1
    assert accounts.principal(session) is None
    now[0] = 0
    session = accounts.login("ana", "secret")
    accounts.logout(session)
    assert accounts.principal(session) is None


def test_lockout_after_repeated_failures_then_recovers() -> None:
    now = [0.0]
    accounts = make(now)
    for _ in range(MAX_FAILURES):
        assert accounts.login("ana", "bad") is None
    assert accounts.login("ana", "secret") is None  # locked even with the right password
    now[0] = LOCKOUT_SECONDS + 1
    assert accounts.login("ana", "secret")


def test_parse_users_rejects_bad_entries() -> None:
    import pytest

    stored = hash_password("x")
    assert parse_users(f"a:{stored}:customer:cust_010")["a"][1].customer_id == "cust_010"
    for bad in (f"a:{stored}:wizard", f"a:{stored}:fraud_analyst:cust_1", "a:b"):
        with pytest.raises(ValueError):
            parse_users(bad)
