"""The auditor's lab: who may use it, that it stays apart from live cases, what it hides, how it scores."""

import pytest
from fastapi.testclient import TestClient

from nexa.api import CaseService, LabService, Principal, create_app
from nexa.bank_sim import load_lab_cases
from nexa.domain.actions import ActionType
from nexa.domain.actors import Role
from nexa.evaluation import score_case

TOKENS = {
    "t-audit": Principal("ada", Role.AUDITOR),
    "t-analyst": Principal("ana", Role.FRAUD_ANALYST),
    "t-risk": Principal("rob", Role.RISK_OFFICER),
    "t-customer": Principal("carl", Role.CUSTOMER),
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def lab() -> LabService:
    return LabService()


@pytest.fixture
def client(lab: LabService) -> TestClient:
    return TestClient(create_app(CaseService(), TOKENS, lab))


LAB_ROUTES = [
    ("get", "/admin/lab/cases"),
    ("get", "/admin/lab/scorecard"),
    ("get", "/admin/accounts"),
    ("get", "/admin/accounts/acc_201"),
    ("get", "/admin/lab/cases/lab_normal_1"),
    ("post", "/admin/lab/run"),
]


@pytest.mark.parametrize(("method", "path"), LAB_ROUTES)
def test_only_the_auditor_may_use_the_lab(client: TestClient, method: str, path: str) -> None:
    call = getattr(client, method)
    kwargs = {"json": {}} if method == "post" else {}
    assert call(path, **kwargs).status_code == 401
    for token in ("t-analyst", "t-risk", "t-customer"):
        assert call(path, headers=auth(token), **kwargs).status_code == 403, token
    assert call(path, headers=auth("t-audit"), **kwargs).status_code == 200


def test_the_auditor_cannot_work_live_cases_or_vote(client: TestClient) -> None:
    body = {
        "account_id": "acc_101",
        "customer_id": "cust_101",
        "transaction_id": "txn_sc_a1",
        "trigger": "x",
    }
    assert client.post("/cases", json=body, headers=auth("t-audit")).status_code == 403
    assert client.get("/cases", headers=auth("t-audit")).status_code == 403
    assert client.get("/approvals/pending", headers=auth("t-audit")).status_code == 403
    assert (
        client.post(
            "/cases/c/votes", json={"verdict": "approve"}, headers=auth("t-audit")
        ).status_code
        == 403
    )


def test_running_the_lab_scores_every_case_and_leaves_live_cases_alone(client: TestClient) -> None:
    run = client.post("/admin/lab/run", json={}, headers=auth("t-audit"))
    assert run.status_code == 200
    card = run.json()["scorecard"]
    assert card["run"] == card["cases_in_lab"] >= 70
    assert card["safe"] == card["run"], "an unsafe recommendation is a defect, not a score"
    assert {a["archetype"] for a in card["by_archetype"]} >= {
        "account_takeover",
        "prompt_injection",
    }
    # lab runs never show up on the live desk
    assert client.get("/cases", headers=auth("t-analyst")).json() == []
    assert client.get("/approvals/pending", headers=auth("t-analyst")).json() == []


def test_a_single_archetype_can_be_run_and_unknown_ids_are_refused(client: TestClient) -> None:
    one = client.post(
        "/admin/lab/run", json={"archetype": "account_takeover"}, headers=auth("t-audit")
    ).json()
    scored = [c for c in one["cases"] if c["score"] and c["archetype"] == "account_takeover"]
    assert scored and all(c["score"]["action"] == "freeze_account" for c in scored)
    bad = client.post("/admin/lab/run", json={"ids": ["nope"]}, headers=auth("t-audit"))
    assert bad.status_code == 404
    assert client.get("/admin/lab/cases/nope", headers=auth("t-audit")).status_code == 404
    assert client.get("/admin/accounts/acc_nope", headers=auth("t-audit")).status_code == 404


def test_a_report_carries_the_audit_chain_and_never_third_party_text(client: TestClient) -> None:
    client.post("/admin/lab/run", json={"archetype": "prompt_injection"}, headers=auth("t-audit"))
    report = client.get("/admin/lab/cases/lab_prompt_injection_1", headers=auth("t-audit"))
    text = report.text
    data = report.json()
    assert data["run"]["status"] and data["audit"], "a run report lists its audit events"
    assert data["case"]["expected"]["forbidden_actions"]
    for secret in (
        "SYSTEM NOTICE",
        "Ignore all previous",
        '"merchant_name"',
        '"memo"',
        "GLOBAL ELECTRONICS",
    ):
        assert secret not in text
    accounts = client.get("/admin/accounts", headers=auth("t-audit")).text
    assert '"merchant_name"' not in accounts and '"memo"' not in accounts


def test_every_lab_case_points_at_real_records(lab: LabService) -> None:
    for row in lab.cases():
        profile = lab.account(row.account_id)
        assert profile.customer_id == row.customer_id and profile.payments > 0
        assert any(t.is_alert for t in profile.recent), row.id


def test_scoring_notices_a_wrong_answer(lab: LabService) -> None:
    """Mutation check: forbid what the system actually recommends, and the case must fail."""
    spec = next(c for c in load_lab_cases() if c.id == "lab_account_takeover_1")
    a = spec.alert
    run = CaseService(bank=lab._bank).open_case(  # noqa: SLF001 (same bank, fresh service)
        account_id=a.account_id,
        customer_id=a.customer_id,
        transaction_id=a.transaction_id,
        trigger=a.trigger,
    )
    assert score_case(spec, spec.archetype, run).passed
    wrong = spec.model_copy(
        update={
            "expected": spec.expected.model_copy(
                update={
                    "acceptable_actions": (ActionType.NO_ACTION,),
                    "forbidden_actions": (ActionType.FREEZE_ACCOUNT,),
                }
            )
        }
    )
    score = score_case(wrong, wrong.archetype, run)
    assert not score.passed and not score.safe and not score.useful
