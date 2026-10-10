from datetime import UTC, datetime, timedelta

import pytest

from nexa.bank_sim import DuplicateRecordError, InMemoryBank, RecordNotFoundError
from nexa.bank_sim.models import (
    AccountRecord,
    AccountStatus,
    CardStatus,
    Channel,
    CustomerRecord,
    Direction,
    KycRecord,
    KycStatus,
    RiskTier,
    TransactionRecord,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def make_customer(cid: str = "c1") -> CustomerRecord:
    return CustomerRecord(
        id=cid, full_name="Test User", risk_tier=RiskTier.LOW, segment="retail",
        home_country="PK", home_city="Karachi", address="1 Test Road",
        phone="+92-300-0000000", email="t@example.test",
    )  # fmt: skip


def make_account(aid: str = "a1", cid: str = "c1") -> AccountRecord:
    return AccountRecord(
        id=aid, customer_id=cid, product="current", balance=1000, opened_on=T0.date()
    )


def make_txn(tid: str, minutes: int, account: str = "a1") -> TransactionRecord:
    return TransactionRecord(
        id=tid, account_id=account, occurred_at=T0 + timedelta(minutes=minutes),
        direction=Direction.DEBIT, amount=100, merchant_name="Shop", merchant_category="retail",
        country="PK", city="Karachi", channel=Channel.POS,
    )  # fmt: skip


def make_bank() -> InMemoryBank:
    return InMemoryBank(
        customers=[make_customer()],
        accounts=[make_account(), make_account("a2")],
        transactions=[make_txn("t3", 30), make_txn("t1", 10), make_txn("t2", 20)],
        kyc=[KycRecord(customer_id="c1", status=KycStatus.VERIFIED)],
    )


def test_lookups_return_records() -> None:
    bank = make_bank()
    assert bank.get_customer("c1").full_name == "Test User"
    assert bank.get_account("a1").customer_id == "c1"
    assert bank.get_transaction("t1").amount == 100
    assert bank.get_kyc("c1").status is KycStatus.VERIFIED
    assert {a.id for a in bank.list_accounts("c1")} == {"a1", "a2"}
    assert bank.list_accounts("nobody") == ()


@pytest.mark.parametrize(
    "call",
    [
        lambda b: b.get_customer("x"),
        lambda b: b.get_account("x"),
        lambda b: b.get_transaction("x"),
        lambda b: b.get_kyc("x"),
        lambda b: b.list_transactions("x"),
        lambda b: b.freeze_account("x"),
    ],
)
def test_unknown_ids_raise(call: object) -> None:
    with pytest.raises(RecordNotFoundError):
        call(make_bank())  # type: ignore[operator]


def test_transactions_are_oldest_first_and_filterable() -> None:
    bank = make_bank()
    assert [t.id for t in bank.list_transactions("a1")] == ["t1", "t2", "t3"]
    window = bank.list_transactions(
        "a1", since=T0 + timedelta(minutes=15), until=T0 + timedelta(minutes=25)
    )
    assert [t.id for t in window] == ["t2"]
    assert bank.list_transactions("a2") == ()


def test_freeze_and_block_change_only_the_target_account() -> None:
    bank = make_bank()
    frozen = bank.freeze_account("a1")
    assert frozen.status is AccountStatus.FROZEN
    assert bank.get_account("a1").status is AccountStatus.FROZEN
    assert bank.get_account("a2").status is AccountStatus.ACTIVE
    blocked = bank.block_card("a2")
    assert blocked.card_status is CardStatus.BLOCKED
    assert bank.get_account("a1").card_status is CardStatus.ACTIVE


def test_actions_are_idempotent() -> None:
    bank = make_bank()
    assert bank.freeze_account("a1") == bank.freeze_account("a1")
    assert bank.block_card("a1") == bank.block_card("a1")


def test_duplicate_ids_in_seed_data_are_rejected() -> None:
    with pytest.raises(DuplicateRecordError, match="account"):
        InMemoryBank([make_customer()], [make_account(), make_account()], [], [])


def test_records_cannot_be_mutated_by_callers() -> None:
    account = make_bank().get_account("a1")
    with pytest.raises(Exception, match="frozen"):
        account.balance = 0  # type: ignore[misc]
