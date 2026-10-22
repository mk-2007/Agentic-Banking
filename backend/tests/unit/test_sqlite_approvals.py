"""The SQLite approval store behaves like the in-memory one and survives a restart."""

from datetime import timedelta
from pathlib import Path

import pytest

from nexa.approvals import SqliteApprovalStore
from nexa.domain.actions import ActionType
from nexa.domain.actors import Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.domain.clock import utc_now

NOW = utc_now()


def request(approval_id: str = "apr_1") -> ApprovalRequest:
    now = NOW
    return ApprovalRequest(
        id=approval_id, case_id="case_f", decision_id="dec_1", target_account_id="acc_106",
        action=ActionType.FREEZE_ACCOUNT, risk_level=4,
        required_roles=(Role.FRAUD_ANALYST, Role.RISK_OFFICER),
        requested_at=now, expires_at=now + timedelta(hours=1),
    )  # fmt: skip


def test_roundtrip_duplicate_and_unknown(tmp_path: Path) -> None:
    store = SqliteApprovalStore(tmp_path / "a.db")
    store.add_request(request())
    assert store.get_request("apr_1") == request()
    assert store.get_request("nope") is None and store.get_votes("nope") == ()
    with pytest.raises(ValueError):
        store.add_request(request())
    with pytest.raises(KeyError):
        store.set_votes("nope", [])


def test_votes_and_single_use_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    store = SqliteApprovalStore(path)
    store.add_request(request())
    vote = ApprovalVote(
        request_id="apr_1", approver_id="ana", role=Role.FRAUD_ANALYST,
        verdict=Verdict.APPROVE, decided_at=utc_now(),
    )  # fmt: skip
    store.set_votes("apr_1", [vote])
    assert store.try_consume("apr_1") and not store.try_consume("apr_1")
    reopened = SqliteApprovalStore(path)
    assert [v.approver_id for v in reopened.get_votes("apr_1")] == ["ana"]
    assert not reopened.try_consume("apr_1")  # spent before the restart, spent forever
    assert not reopened.try_consume("unknown")
