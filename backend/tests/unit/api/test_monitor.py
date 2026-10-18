"""The monitor: every payment is reviewed, and the floor, the routine rule and the model share the work."""

import json
import threading
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from nexa.agents.monitor_agent import (
    FloorReason,
    MonitorAgent,
    Triage,
    TriageReason,
    floor_reasons,
    is_routine,
)
from nexa.api import CaseService, Monitor, Principal, create_app
from nexa.api.monitor import build_digest
from nexa.bank_sim.models import Channel, Direction, TransactionRecord
from nexa.config import DEFAULT_THRESHOLDS as T
from nexa.domain.actors import Role
from nexa.llm import LlmGateway, LlmRequest, ScriptedProvider

ACCOUNT = "acc_010"  # an ordinary customer: about 40 payments, the usual one around PKR 16,000
TOKENS = {
    "t-cust": Principal("ayesha", Role.CUSTOMER, "cust_010"),
    "t-analyst": Principal("ana", Role.FRAUD_ANALYST),
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Inline(Executor):
    """Runs the review at once, so a test can look at the result straight after the payment."""

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        future: Future[None] = Future()
        fn(*args, **kwargs)
        future.set_result(None)
        return future


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


def triage_model(open_case: bool, reason: str) -> ScriptedProvider:
    return ScriptedProvider(lambda r: json.dumps({"open_case": open_case, "reason": reason}))


class Setup:
    def __init__(self, model: ScriptedProvider | None = None) -> None:
        self.clock = Clock()
        self.service = CaseService(clock=self.clock)
        self.model = model
        gateway = LlmGateway([model], sleep=lambda s: None) if model else None
        self.monitor = Monitor(
            self.service.bank,
            self.service,
            MonitorAgent(gateway, T),
            executor=Inline(),
        )
        self.client = TestClient(create_app(self.service, TOKENS, monitor=self.monitor))

    def pay(self, **changes: object) -> dict:  # type: ignore[type-arg]
        body: dict[str, object] = {
            "account_id": ACCOUNT,
            "amount": 2500,
            "merchant_name": "Imtiaz Super Market",
            "merchant_category": "grocery",
            "country": "PK",
            "city": "Karachi",
            "channel": "pos",
            **changes,
        }
        response = self.client.post("/app/payments", json=body, headers=auth("t-cust"))
        assert response.status_code == 201, response.text
        return response.json()  # type: ignore[no-any-return]

    def last(self):  # type: ignore[no-untyped-def]
        return self.monitor.entries()[0]


GREY = {"country": "AE", "city": "Dubai", "amount": 8000}  # abroad, not routine, no threshold hit


# --- the three ways a payment is decided -------------------------------------------------------------
def test_an_ordinary_payment_is_cleared_without_a_case_or_a_model() -> None:
    s = Setup(triage_model(True, "unusual_pattern"))
    s.pay()
    e = s.last()
    assert (e.decision.value, e.path.value, e.reasons) == ("cleared", "routine", ("routine",))  # type: ignore[union-attr]
    assert s.service.all_runs() == [] and s.model.calls == 0  # type: ignore[union-attr]


def test_a_payment_over_a_threshold_always_opens_a_case() -> None:
    s = Setup(triage_model(False, "nothing_unusual"))  # a model that would clear everything
    s.pay(
        channel="mobile_app", merchant_category="transfer", payee_account="PK-901",
        device="new", failed_logins=4, amount=20000,
    )  # fmt: skip
    e = s.last()
    assert e.decision.value == "opened" and e.path.value == "floor"  # type: ignore[union-attr]
    assert {"failed_logins", "new_payee_on_unknown_device"} <= set(e.reasons)
    assert s.model.calls == 0  # type: ignore[union-attr]  # the floor never asks the model
    run = s.service.get(e.case_id)  # type: ignore[arg-type]
    assert run.case.alert.trigger.startswith("monitor:floor:")
    assert run.decision is not None


def test_a_model_decides_the_grey_zone_and_gives_a_reason() -> None:
    s = Setup(triage_model(True, "location_concern"))
    s.pay(**GREY)
    e = s.last()
    assert (e.decision.value, e.path.value, e.reasons) == ("opened", "model", ("location_concern",))  # type: ignore[union-attr]
    assert s.service.get(e.case_id).case.alert.trigger == "monitor:model:location_concern"  # type: ignore[arg-type]

    s2 = Setup(triage_model(False, "nothing_unusual"))
    s2.pay(**GREY)
    assert s2.last().decision.value == "cleared" and s2.service.all_runs() == []  # type: ignore[union-attr]


def test_with_no_model_the_grey_zone_opens_a_case_rather_than_guessing() -> None:
    s = Setup(None)
    s.pay(**GREY)
    e = s.last()
    assert (e.decision.value, e.path.value) == ("opened", "model_unavailable")  # type: ignore[union-attr]


def test_a_model_that_answers_badly_also_opens_the_case() -> None:
    s = Setup(ScriptedProvider(["not json"] * 3))
    s.pay(**GREY)
    assert s.last().path.value == "model_unavailable"  # type: ignore[union-attr]


# --- a burst is one case, until something new happens ------------------------------------------------
def test_a_burst_links_to_its_case_and_a_new_reason_opens_another() -> None:
    s = Setup(None)
    kind = {
        "channel": "mobile_app", "merchant_category": "transfer", "payee_account": "PK-777",
        "device": "new", "failed_logins": 4, "amount": 6000,
    }  # fmt: skip
    outcomes = []
    for _ in range(5):
        s.pay(**kind)
        s.clock.now += timedelta(minutes=2)
        outcomes.append(s.last().decision.value)  # type: ignore[union-attr]
    assert outcomes[:4] == ["opened", "linked", "linked", "linked"]
    assert outcomes[4] == "opened"  # the fifth payment in an hour is a reason the case did not have
    assert "rapid_payments" in s.last().reasons
    assert len(s.service.all_runs()) == 2


# --- safety of the review itself ------------------------------------------------------------------------
def test_a_failing_review_never_fails_the_payment() -> None:
    s = Setup(None)

    def boom(**_: object) -> None:
        raise RuntimeError("down")

    s.service.open_case = boom  # type: ignore[method-assign,assignment]
    s.pay(**GREY)
    assert s.last().decision.value == "error"  # type: ignore[union-attr]
    assert s.client.get("/app/me", headers=auth("t-cust")).json()["recent"][0]["amount"] == 8000


def test_the_log_is_for_employees_and_holds_no_text() -> None:
    s = Setup(None)
    s.pay(**GREY)
    assert s.client.get("/monitor/log", headers=auth("t-cust")).status_code == 403
    assert s.client.get("/monitor/log").status_code == 401
    rows = s.client.get("/monitor/log", headers=auth("t-analyst")).json()
    assert len(rows) == 1 and rows[0]["decision"] == "opened" and rows[0]["case_id"]
    assert "Imtiaz" not in json.dumps(rows) and "merchant" not in json.dumps(rows)


def test_the_log_is_empty_when_the_monitor_is_off() -> None:
    client = TestClient(create_app(CaseService(), TOKENS))
    assert client.get("/monitor/log", headers=auth("t-analyst")).json() == []


# --- the digest and the rules on it ----------------------------------------------------------------------
def make(service: CaseService, i: int, amount: int, **changes: object) -> TransactionRecord:
    fields: dict[str, object] = {
        "id": f"t_{i}", "account_id": ACCOUNT, "occurred_at": datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
        "direction": Direction.DEBIT, "amount": amount, "merchant_name": "X Shop",
        "merchant_category": "retail", "country": "PK", "city": "Karachi", "channel": Channel.POS,
        "device_id": "dev_010_1", "device_trusted": True,
    }  # fmt: skip
    return TransactionRecord(**{**fields, **changes})  # type: ignore[arg-type]


def test_the_digest_is_numbers_and_flags_only() -> None:
    service = CaseService()
    d = build_digest(service.bank, make(service, 1, 2500), T)
    assert all(isinstance(v, int | float | bool | str | None) for v in d.model_dump().values())
    assert set(d.model_dump()) == {
        "transaction_id", "direction", "channel", "amount", "prior_transactions", "ratio_to_average",
        "payments_last_hour", "payments_last_day", "total_last_day", "near_line_last_day",
        "new_payee", "device_trusted", "failed_logins", "abroad", "travel_notice_covers",
        "country_seen_before", "merchant_seen_before", "share_of_balance",
    }  # fmt: skip
    assert d.prior_transactions >= 20 and d.ratio_to_average == pytest.approx(0.2, abs=0.1)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"amount": 300_000}, {FloorReason.HIGH_VALUE, FloorReason.AMOUNT_ABOVE_AVERAGE}),
        ({"amount": 90_000}, {FloorReason.AMOUNT_ABOVE_AVERAGE}),
        ({"failed_auth_attempts_prior_hour": 3}, {FloorReason.FAILED_LOGINS}),
        (
            {"is_new_beneficiary": True, "device_trusted": False, "channel": Channel.WEB},
            {FloorReason.NEW_PAYEE_ON_UNKNOWN_DEVICE},
        ),
        ({"amount": 2500}, set()),
    ],
)
def test_the_floor_names_every_threshold_a_payment_crosses(
    changes: dict[str, object], expected: set[FloorReason]
) -> None:
    service = CaseService()
    amount = int(changes.pop("amount", 2500))  # type: ignore[call-overload]
    d = build_digest(service.bank, make(service, 1, amount, **changes), T)
    assert set(floor_reasons(d, T)) == expected


def test_routine_is_narrow() -> None:
    service = CaseService()
    base = build_digest(service.bank, make(service, 1, 2500), T)
    assert is_routine(base, T)
    for change in (
        {"failed_logins": 1}, {"new_payee": True}, {"abroad": True}, {"amount": 200_000},
        {"near_line_last_day": 2}, {"ratio_to_average": 3.0}, {"ratio_to_average": None},
        {"prior_transactions": 3}, {"payments_last_hour": 3},
    ):  # fmt: skip
        assert not is_routine(base.model_copy(update=change), T), change
    online = base.model_copy(update={"channel": "web", "device_trusted": False})
    assert not is_routine(online, T)


def test_the_digest_sees_a_cluster_just_under_the_line() -> None:
    service = CaseService()
    t0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    deposits = [
        make(
            service, 100 + i, 190_000, occurred_at=t0 + timedelta(hours=i),
            direction=Direction.CREDIT, channel=Channel.TRANSFER, device_trusted=False,
        )
        for i in range(4)
    ]  # fmt: skip
    for d in deposits[:3]:
        service.bank.add_transaction(d)
    d = build_digest(service.bank, deposits[3], T)
    assert d.near_line_last_day == 4 and d.payments_last_day == 4


def test_a_triage_must_open_with_a_concern_or_clear_with_nothing_unusual() -> None:
    with pytest.raises(ValueError):
        Triage(open_case=True, reason=TriageReason.NOTHING_UNUSUAL)
    with pytest.raises(ValueError):
        Triage(open_case=False, reason=TriageReason.UNUSUAL_AMOUNT)
    assert Triage(open_case=True, reason=TriageReason.NEAR_THRESHOLD_CLUSTER).open_case


def test_the_model_prompt_carries_the_digest_and_no_free_text() -> None:
    seen: list[LlmRequest] = []

    def model(request: LlmRequest) -> str:
        seen.append(request)
        return json.dumps({"open_case": False, "reason": "nothing_unusual"})

    s = Setup(ScriptedProvider(model))
    s.pay(merchant_name="Totally Secret Merchant", **GREY)
    text = " ".join(m.content for r in seen for m in r.messages)
    assert "ratio_to_average" in text and "Secret" not in text and "Dubai" not in text


# --- a slow investigation does not freeze the desk ---------------------------------------------------------
def test_listing_and_voting_work_while_another_case_is_still_being_investigated() -> None:
    entered, release = threading.Event(), threading.Event()

    def slow_model(request: LlmRequest) -> str:
        entered.set()
        release.wait(timeout=10)
        return json.dumps({"action": "conclude", "claims": []})

    service = CaseService(gateway=LlmGateway([ScriptedProvider(slow_model)], sleep=lambda s: None))
    worker = threading.Thread(
        target=lambda: service.open_case(
            account_id="acc_101",
            customer_id="cust_101",
            transaction_id="txn_sc_a1",
            trigger="routine_screening",
        )  # fmt: skip
    )
    worker.start()
    try:
        assert entered.wait(timeout=10)
        done = threading.Event()
        threading.Thread(target=lambda: (service.all_runs(), service.pending(), done.set())).start()
        assert done.wait(timeout=3), "listing cases must not wait for an investigation"
    finally:
        release.set()
        worker.join(timeout=30)
    assert len(service.all_runs()) == 1


def test_a_growing_cluster_under_the_line_gets_a_case_each_time_it_grows() -> None:
    s = Setup(None)  # no model: every grey-zone payment opens a case, so linking is what is tested
    t0 = s.clock.now
    outcomes = []
    for i in range(4):
        deposit = make(
            s.service, 200 + i, 190_000, occurred_at=t0 + timedelta(minutes=10 * i),
            direction=Direction.CREDIT, channel=Channel.ATM, device_trusted=False,
        )  # fmt: skip
        s.service.bank.add_transaction(deposit)
        s.monitor.watch(deposit)
        outcomes.append(s.last().decision.value)  # type: ignore[union-attr]
    assert outcomes == ["opened", "opened", "opened", "opened"]  # each saw a bigger cluster
    assert len(s.service.all_runs()) == 4
