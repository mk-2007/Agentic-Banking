"""The HTTP API: who may call what, the whole Level 4 path over HTTP, and what must stay hidden."""

import pytest
from fastapi.testclient import TestClient

from nexa.api import CaseService, Principal, create_app, parse_tokens
from nexa.bank_sim import load_scenarios
from nexa.domain.actors import Role

TOKENS = {
    "t-analyst": Principal("ana", Role.FRAUD_ANALYST),
    "t-risk": Principal("rob", Role.RISK_OFFICER),
    "t-risk2": Principal("rita", Role.RISK_OFFICER),
    "t-customer": Principal("carl", Role.CUSTOMER),
}
SCENARIOS = {s.id: s for s in load_scenarios()}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def service() -> CaseService:
    return CaseService()


@pytest.fixture
def client(service: CaseService) -> TestClient:
    return TestClient(create_app(service, TOKENS))


def alert_body(scenario_id: str) -> dict[str, str]:
    a = SCENARIOS[scenario_id].alert
    return {
        "account_id": a.account_id,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
        "trigger": a.trigger,
    }


def open_case(client: TestClient, scenario_id: str) -> dict:  # type: ignore[type-arg]
    response = client.post("/cases", json=alert_body(scenario_id), headers=auth("t-analyst"))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# --- authentication and roles ---------------------------------------------------------------
def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/cases"), ("get", "/cases/x"), ("get", "/approvals/pending"), ("post", "/chat")],
)
def test_every_other_route_rejects_a_missing_or_wrong_token(
    client: TestClient, method: str, path: str
) -> None:
    for headers in ({}, auth("nope"), {"Authorization": "Basic t-analyst"}):
        response = getattr(client, method)(path, headers=headers)
        assert response.status_code == 401


def test_a_customer_cannot_open_view_or_vote_on_cases(client: TestClient) -> None:
    customer = auth("t-customer")
    assert (
        client.post("/cases", json=alert_body("scenario_a_normal"), headers=customer).status_code
        == 403
    )
    assert client.get("/cases", headers=customer).status_code == 403
    assert client.get("/approvals/pending", headers=customer).status_code == 403
    assert (
        client.post("/cases/x/votes", json={"verdict": "approve"}, headers=customer).status_code
        == 403
    )


# --- opening and viewing cases ---------------------------------------------------------------
def test_a_low_risk_case_runs_to_decision_ready(client: TestClient) -> None:
    case = open_case(client, "scenario_a_normal")
    assert case["status"] == "decision_ready" and case["failure"] is None
    assert case["decision"]["recommended_action"] == "no_action" and case["approval"] is None
    assert case["trail"][0] == "created" and case["trail"][-1] == "decision_ready"
    assert case["findings"] and all(f["code"] for f in case["findings"])


def test_an_alert_that_does_not_match_the_bank_is_rejected(client: TestClient) -> None:
    body = alert_body("scenario_a_normal")
    mismatch = client.post(
        "/cases", json={**body, "customer_id": "cust_999"}, headers=auth("t-analyst")
    )
    assert mismatch.status_code == 422
    unknown = client.post(
        "/cases", json={**body, "transaction_id": "txn_nope"}, headers=auth("t-analyst")
    )
    assert unknown.status_code == 404


def test_unknown_fields_and_bad_values_are_rejected(client: TestClient) -> None:
    body = {**alert_body("scenario_a_normal"), "status": "approved"}
    assert client.post("/cases", json=body, headers=auth("t-analyst")).status_code == 422
    assert (
        client.post("/chat", json={"question": "x"}, headers=auth("t-customer")).status_code == 422
    )


def test_responses_never_carry_third_party_text(client: TestClient) -> None:
    case = open_case(client, "scenario_x_prompt_injection")
    text = client.get(f"/cases/{case['id']}", headers=auth("t-analyst")).text
    assert "Ignore all previous instructions" not in text and "ACME TRADERS" not in text
    audit = client.get(f"/cases/{case['id']}/audit", headers=auth("t-analyst")).text
    assert "Ignore all previous instructions" not in audit


def test_unknown_cases_are_404(client: TestClient) -> None:
    for path in ("/cases/nope", "/cases/nope/audit"):
        assert client.get(path, headers=auth("t-analyst")).status_code == 404
    vote = client.post("/cases/nope/votes", json={"verdict": "approve"}, headers=auth("t-analyst"))
    assert vote.status_code == 404


# --- the Level 4 path over HTTP ---------------------------------------------------------------
def test_an_account_takeover_needs_two_different_roles_and_then_freezes(
    client: TestClient, service: CaseService
) -> None:
    case = open_case(client, "scenario_f_account_takeover")
    cid, account = case["id"], case["account_id"]
    assert case["status"] == "waiting_for_approval"
    assert case["decision"]["recommended_action"] == "freeze_account"
    assert set(case["approval"]["required_roles"]) == {"fraud_analyst", "risk_officer"}
    assert cid in [c["id"] for c in client.get("/approvals/pending", headers=auth("t-risk")).json()]

    first = client.post(
        f"/cases/{cid}/votes", json={"verdict": "approve"}, headers=auth("t-analyst")
    )
    assert first.json()["status"] == "waiting_for_approval"
    assert service.bank.get_account(account).status.value == "active"  # one approver is not enough

    second = client.post(f"/cases/{cid}/votes", json={"verdict": "approve"}, headers=auth("t-risk"))
    done = second.json()
    assert done["status"] == "completed" and done["failure"] is None
    assert [v["role"] for v in done["approval"]["votes"]] == ["fraud_analyst", "risk_officer"]
    assert service.bank.get_account(account).status.value == "frozen"

    events = [
        e["event_type"] for e in client.get(f"/cases/{cid}/audit", headers=auth("t-analyst")).json()
    ]
    assert "approval_requested" in events and events.count("approval_vote_cast") == 2
    assert events.count("action_executed") == 1
    again = client.post(f"/cases/{cid}/votes", json={"verdict": "approve"}, headers=auth("t-risk"))
    assert again.status_code == 409  # the case is no longer waiting


def test_the_voter_and_role_come_from_the_token_not_the_body(client: TestClient) -> None:
    case = open_case(client, "scenario_f_account_takeover")
    body = {"verdict": "approve", "approver_id": "someone", "role": "risk_officer"}
    assert (
        client.post(f"/cases/{case['id']}/votes", json=body, headers=auth("t-analyst")).status_code
        == 422
    )
    ok = client.post(
        f"/cases/{case['id']}/votes", json={"verdict": "approve"}, headers=auth("t-analyst")
    )
    vote = ok.json()["approval"]["votes"][0]
    assert vote["approver_id"] == "ana" and vote["role"] == "fraud_analyst"


def test_one_role_voting_twice_does_not_make_two_approvers(
    client: TestClient, service: CaseService
) -> None:
    case = open_case(client, "scenario_f_account_takeover")
    for token in ("t-risk", "t-risk2"):
        run = client.post(
            f"/cases/{case['id']}/votes", json={"verdict": "approve"}, headers=auth(token)
        )
    assert run.json()["status"] == "waiting_for_approval"
    assert service.bank.get_account(case["account_id"]).status.value == "active"


def test_a_rejection_ends_the_case_and_changes_nothing(
    client: TestClient, service: CaseService
) -> None:
    case = open_case(client, "scenario_f_account_takeover")
    done = client.post(
        f"/cases/{case['id']}/votes",
        json={"verdict": "reject", "comment": "looks fine"},
        headers=auth("t-analyst"),
    ).json()
    assert done["status"] == "rejected_by_human"
    assert service.bank.get_account(case["account_id"]).status.value == "active"


def test_voting_on_a_case_that_never_needed_approval_is_a_conflict(client: TestClient) -> None:
    case = open_case(client, "scenario_a_normal")
    response = client.post(
        f"/cases/{case['id']}/votes", json={"verdict": "approve"}, headers=auth("t-analyst")
    )
    assert response.status_code == 409


# --- chat: the channel comes from who is asking -------------------------------------------------
def test_a_customer_gets_public_knowledge_only(client: TestClient) -> None:
    answer = client.post(
        "/chat", json={"question": "how do I block my debit card"}, headers=auth("t-customer")
    )
    assert answer.status_code == 200
    passages = answer.json()["passages"]
    assert passages and all(p["document_id"] and p["version"] for p in passages)


def test_a_customer_cannot_reach_restricted_policy_by_asking(client: TestClient) -> None:
    question = {
        "question": "risk indicators and thresholds unusual amount rapid series failed authentication"
    }
    customer = client.post("/chat", json=question, headers=auth("t-customer")).json()["passages"]
    employee = client.post("/chat", json=question, headers=auth("t-analyst")).json()["passages"]
    assert "NB-POL-FRAUD-001" not in {p["document_id"] for p in customer}
    assert "NB-POL-FRAUD-001" in {p["document_id"] for p in employee}


def test_chat_is_audited_through_the_tool_layer(client: TestClient, service: CaseService) -> None:
    before = len(service.log.events())
    client.post(
        "/chat", json={"question": "what is the daily transfer limit"}, headers=auth("t-customer")
    )
    assert any(e.tool_name == "search_knowledge_base" for e in service.log.events()[before:])
    assert service.log.verify() is None


# --- tokens -------------------------------------------------------------------------------------
def test_tokens_parse_and_reject_bad_input() -> None:
    found = parse_tokens("a:ana:fraud_analyst, b:carl:customer")
    assert found["a"].is_employee and not found["b"].is_employee
    for bad in (
        "a:ana",
        "a:ana:wizard",
        "a:ana:data_agent",
        "a:ana:customer,a:bob:customer",
        "a::customer",
    ):
        with pytest.raises(ValueError):
            parse_tokens(bad)
    assert parse_tokens("") == {}


# --- dashboard ------------------------------------------------------------------------------
def test_dashboard_page_is_served_and_scenarios_need_an_employee(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "NexaBank" in page.text
    assert client.get("/scenarios").status_code == 401
    assert client.get("/scenarios", headers=auth("t-customer")).status_code == 403
    rows = client.get("/scenarios", headers=auth("t-analyst")).json()
    assert len(rows) == len(SCENARIOS)
    body = {k: rows[0][k] for k in ("account_id", "customer_id", "transaction_id", "trigger")}
    assert client.post("/cases", json=body, headers=auth("t-analyst")).status_code == 201


def test_dashboard_uses_the_real_waiting_status(client: TestClient) -> None:
    # The page shows vote buttons only for this exact status; a typo hid them (found in a browser run).
    page = client.get("/").text
    assert '"waiting_for_approval"' in page and "awaiting" not in page
