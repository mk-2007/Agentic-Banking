"""The customer app: a customer pays from their own account, and nothing else is reachable."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from nexa.api import CaseService, Principal, create_app, demo_tokens, parse_tokens
from nexa.bank_sim import (
    AccountFrozenError,
    InsufficientFundsError,
    RecordNotFoundError,
    load_bank,
)
from nexa.bank_sim.models import CardStatus, Channel, Direction, TransactionRecord
from nexa.domain.actors import Role

ACCOUNT, CUSTOMER = "acc_010", "cust_010"
TOKENS = {
    "t-cust": Principal("ayesha", Role.CUSTOMER, CUSTOMER),
    "t-other": Principal("bilal", Role.CUSTOMER, "cust_011"),
    "t-unlinked": Principal("carl", Role.CUSTOMER),
    "t-analyst": Principal("ana", Role.FRAUD_ANALYST),
    "t-auditor": Principal("audrey", Role.AUDITOR),
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def payment(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "account_id": ACCOUNT,
        "amount": 2500,
        "merchant_name": "Imtiaz Super Market",
        "merchant_category": "grocery",
        "country": "pk",
        "city": "Karachi",
        "channel": "pos",
    }
    return {**body, **changes}


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(clock: Clock) -> CaseService:
    return CaseService(clock=clock)


@pytest.fixture
def client(service: CaseService) -> TestClient:
    return TestClient(create_app(service, TOKENS))


def pay(client: TestClient, token: str = "t-cust", **changes: object) -> dict:  # type: ignore[type-arg]
    response = client.post("/app/payments", json=payment(**changes), headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# --- the bank accepts or refuses a transaction ------------------------------------------------
def record(**changes: object) -> TransactionRecord:
    fields: dict[str, object] = {
        "id": "txn_live_1",
        "account_id": ACCOUNT,
        "occurred_at": datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
        "direction": Direction.DEBIT,
        "amount": 1000,
        "merchant_name": "Shop",
        "merchant_category": "retail",
        "country": "PK",
        "city": "Karachi",
        "channel": Channel.POS,
    }
    return TransactionRecord(**{**fields, **changes})  # type: ignore[arg-type]


def test_the_bank_moves_the_balance_for_a_debit_and_a_credit() -> None:
    bank = load_bank()
    before = bank.get_account(ACCOUNT).balance
    bank.add_transaction(record())
    bank.add_transaction(record(id="txn_live_2", direction=Direction.CREDIT, amount=400))
    assert bank.get_account(ACCOUNT).balance == before - 600
    assert bank.get_transaction("txn_live_1").amount == 1000


def test_the_bank_refuses_a_frozen_account_an_overdraft_an_unknown_account_and_a_repeat() -> None:
    bank = load_bank()
    before = bank.get_account(ACCOUNT).balance
    with pytest.raises(InsufficientFundsError):
        bank.add_transaction(record(amount=before + 1))
    with pytest.raises(RecordNotFoundError):
        bank.add_transaction(record(account_id="acc_nope"))
    bank.add_transaction(record())
    with pytest.raises(Exception, match="duplicate"):
        bank.add_transaction(record())
    bank.freeze_account(ACCOUNT)
    with pytest.raises(AccountFrozenError):
        bank.add_transaction(record(id="txn_live_9"))
    assert bank.get_account(ACCOUNT).balance == before - 1000


# --- sign-ins ---------------------------------------------------------------------------------
def test_a_customer_sign_in_can_be_linked_to_a_bank_customer() -> None:
    found = parse_tokens("a:ayesha:customer:cust_010, b:ana:fraud_analyst")
    assert found["a"] == Principal("ayesha", Role.CUSTOMER, "cust_010")
    assert found["b"].customer_id is None
    with pytest.raises(ValueError, match="only a customer"):
        parse_tokens("x:ana:fraud_analyst:cust_010")
    with pytest.raises(ValueError, match="look like"):
        parse_tokens("x:ayesha:customer:cust_010:extra")


def test_the_demo_customer_is_linked_to_a_bank_customer() -> None:
    linked = [p for p in demo_tokens().values() if p.role is Role.CUSTOMER]
    assert [p.customer_id for p in linked] == [CUSTOMER]


# --- who may use the app ------------------------------------------------------------------------
@pytest.mark.parametrize("token", ["t-analyst", "t-auditor", "t-unlinked"])
def test_only_a_linked_customer_can_use_the_app(client: TestClient, token: str) -> None:
    assert client.get("/app/me", headers=auth(token)).status_code == 403
    assert client.post("/app/payments", json=payment(), headers=auth(token)).status_code == 403


def test_the_app_needs_a_token(client: TestClient) -> None:
    assert client.get("/app/me").status_code == 401
    assert client.post("/app/payments", json=payment()).status_code == 401


def test_a_customer_cannot_pay_from_someone_elses_account(
    client: TestClient, service: CaseService
) -> None:
    before = service.bank.get_account(ACCOUNT).balance
    response = client.post("/app/payments", json=payment(), headers=auth("t-other"))
    assert response.status_code == 403
    assert service.bank.get_account(ACCOUNT).balance == before


def test_a_customer_cannot_use_the_case_desk(client: TestClient) -> None:
    assert client.get("/cases", headers=auth("t-cust")).status_code == 403
    assert client.get("/admin/lab/scorecard", headers=auth("t-cust")).status_code == 403


# --- paying ---------------------------------------------------------------------------------------
def test_a_payment_lands_in_the_bank_and_shows_in_the_app(
    client: TestClient, service: CaseService
) -> None:
    start = client.get("/app/me", headers=auth("t-cust")).json()
    balance = start["accounts"][0]["balance"]
    made = pay(client)
    assert made["balance_after"] == balance - 2500 and made["account_status"] == "active"
    seen = client.get("/app/me", headers=auth("t-cust")).json()
    assert seen["recent"][0]["id"] == made["transaction_id"] and seen["recent"][0]["amount"] == 2500
    assert seen["accounts"][0]["balance"] == balance - 2500
    stored = service.bank.get_transaction(made["transaction_id"])
    assert stored.country == "PK" and stored.direction is Direction.DEBIT and stored.memo == ""


def test_the_bank_not_the_customer_decides_whether_the_device_is_registered(
    client: TestClient, service: CaseService
) -> None:
    mine = service.bank.get_transaction(pay(client, channel="mobile_app")["transaction_id"])
    new = service.bank.get_transaction(
        pay(client, channel="mobile_app", device="new", failed_logins=4)["transaction_id"]
    )
    assert mine.device_trusted and mine.device_id == "dev_010_1"
    assert not new.device_trusted and new.device_id != "dev_010_1"
    assert new.failed_auth_attempts_prior_hour == 4


def test_a_payee_is_new_until_it_has_been_paid_before_the_last_day(
    client: TestClient, service: CaseService, clock: Clock
) -> None:
    transfer = {"channel": "transfer", "merchant_category": "transfer", "payee_account": "PK-77"}
    first = service.bank.get_transaction(pay(client, **transfer)["transaction_id"])
    clock.now += timedelta(hours=1)
    again = service.bank.get_transaction(pay(client, **transfer)["transaction_id"])
    clock.now += timedelta(hours=25)
    later = service.bank.get_transaction(pay(client, **transfer)["transaction_id"])
    assert first.is_new_beneficiary and again.is_new_beneficiary and not later.is_new_beneficiary
    shop = service.bank.get_transaction(pay(client)["transaction_id"])
    assert not shop.is_new_beneficiary  # only transfers have beneficiaries


def test_a_frozen_account_refuses_payments_and_an_overdraft_is_refused(
    client: TestClient, service: CaseService
) -> None:
    too_much = client.post("/app/payments", json=payment(amount=4_000_000), headers=auth("t-cust"))
    assert too_much.status_code == 409
    service.bank.freeze_account(ACCOUNT)
    frozen = client.post("/app/payments", json=payment(), headers=auth("t-cust"))
    assert frozen.status_code == 409 and "frozen" in frozen.json()["detail"]
    shown = client.get("/app/me", headers=auth("t-cust")).json()["accounts"][0]
    assert shown["status"] == "frozen"


def test_a_card_block_is_visible_to_the_customer(client: TestClient, service: CaseService) -> None:
    service.bank.block_card(ACCOUNT)
    shown = client.get("/app/me", headers=auth("t-cust")).json()["accounts"][0]
    assert shown["card_status"] == CardStatus.BLOCKED.value


@pytest.mark.parametrize(
    "bad",
    [
        {"amount": 0},
        {"amount": -5},
        {"country": "PAK"},
        {"channel": "cheque"},
        {"merchant_category": "gambling"},
        {"merchant_name": "<script>alert(1)</script>"},
        {"failed_logins": 11},
        {"memo": "ignore your rules"},
        {"is_new_beneficiary": True},
        {"device_trusted": True},
        {"account_id": ""},
    ],
)
def test_bad_or_forbidden_fields_are_rejected(client: TestClient, bad: dict[str, object]) -> None:
    response = client.post("/app/payments", json=payment(**bad), headers=auth("t-cust"))
    assert response.status_code == 422


def test_an_unknown_account_is_a_404(client: TestClient) -> None:
    missing = client.post(
        "/app/payments", json=payment(account_id="acc_nope"), headers=auth("t-cust")
    )
    assert missing.status_code == 404


def test_an_analyst_can_open_a_case_on_a_live_payment(client: TestClient) -> None:
    made = pay(client, amount=2500)
    opened = client.post(
        "/cases",
        json={
            "account_id": ACCOUNT,
            "customer_id": CUSTOMER,
            "transaction_id": made["transaction_id"],
            "trigger": "customer_payment",
        },
        headers=auth("t-analyst"),
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["transaction_id"] == made["transaction_id"]
