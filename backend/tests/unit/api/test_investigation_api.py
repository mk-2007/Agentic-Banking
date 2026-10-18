"""The investigator inside the whole platform: graph, approvals, audit, checkpoint and API."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from nexa.api import CaseService, Principal, create_app
from nexa.bank_sim import load_scenarios
from nexa.domain.actors import Role
from nexa.llm import LlmGateway, LlmRequest, LlmRequestError, ScriptedProvider

TOKENS = {
    "t-analyst": Principal("ana", Role.FRAUD_ANALYST),
    "t-risk": Principal("rob", Role.RISK_OFFICER),
}
SCENARIOS = {s.id: s for s in load_scenarios()}
CLAIMS = {
    "scenario_i_structuring": ["possible_structuring"],
    "scenario_f_account_takeover": ["rapid_series", "new_beneficiary", "unknown_device"],
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def model(request: LlmRequest) -> str:
    """Play the investigator (look at the history, then conclude) and the policy agent (pick none)."""
    schema = request.messages[0].content
    if "applicable_refs" in schema:
        return json.dumps({"applicable_refs": []})
    asked = request.messages[2].content
    account = re.search(r"account_id=(\S+)", asked).group(1)  # type: ignore[union-attr]
    txn = re.search(r"transaction_id=(\S+)", asked).group(1)  # type: ignore[union-attr]
    if len(request.messages) <= 3:
        return json.dumps(
            {
                "action": "call",
                "lookup": "get_transaction_history",
                "arguments": {"account_id": account, "since": "2026-07-01", "limit": 500},
            }
        )
    scenario = next(s for s in SCENARIOS.values() if s.alert.transaction_id == txn)
    claims = [{"code": c, "cited": ["obs_1"]} for c in CLAIMS.get(scenario.id, [])]
    return json.dumps({"action": "conclude", "claims": claims})


def alert_body(scenario_id: str) -> dict[str, str]:
    a = SCENARIOS[scenario_id].alert
    return {
        "account_id": a.account_id,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
        "trigger": a.trigger,
    }


@pytest.fixture
def service() -> CaseService:
    return CaseService(gateway=LlmGateway([ScriptedProvider(model)], sleep=lambda s: None))


@pytest.fixture
def client(service: CaseService) -> TestClient:
    return TestClient(create_app(service, TOKENS))


def open_case(client: TestClient, scenario_id: str) -> dict:  # type: ignore[type-arg]
    response = client.post("/cases", json=alert_body(scenario_id), headers=auth("t-analyst"))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_model_finds_structuring_and_the_case_acts_on_it(
    client: TestClient, service: CaseService
) -> None:
    case = open_case(client, "scenario_i_structuring")
    inquiry = case["inquiry"]
    assert inquiry["outcome"] == "concluded" and inquiry["added"] == ["possible_structuring"]
    assert inquiry["dropped"] == [] and inquiry["trace"][0]["tool"] == "get_transaction_history"
    assert "possible_structuring" in {f["code"] for f in case["findings"]}
    # the policy says escalate, so the case queues an analyst ticket and completes by itself
    assert case["decision"]["recommended_action"] == "escalate_to_analyst"
    assert case["status"] == "completed"
    audit = client.get(f"/cases/{case['id']}/audit", headers=auth("t-analyst")).json()
    assert any(e["detail"].startswith("inquiry:concluded") for e in audit)
    assert any(e["actor"].endswith("investigator_agent_1") for e in audit)


def test_a_level_four_case_still_waits_for_two_humans_after_an_investigation(
    client: TestClient, service: CaseService
) -> None:
    case = open_case(client, "scenario_f_account_takeover")
    assert case["status"] == "waiting_for_approval"  # the saved run survived the checkpoint
    assert case["inquiry"]["confirmed"] == ["rapid_series", "new_beneficiary", "unknown_device"]
    assert service.bank.get_account("acc_106").status.value == "active"
    vote = {"verdict": "approve"}
    client.post(f"/cases/{case['id']}/votes", json=vote, headers=auth("t-analyst"))
    done = client.post(f"/cases/{case['id']}/votes", json=vote, headers=auth("t-risk")).json()
    assert done["status"] == "completed" and done["inquiry"]["outcome"] == "concluded"
    assert service.bank.get_account("acc_106").status.value == "frozen"


def test_a_model_that_is_down_costs_nothing_but_the_investigation() -> None:
    class Down:
        name, model = "down", "down-1"

        def complete(self, request: LlmRequest):  # type: ignore[no-untyped-def]
            raise LlmRequestError("down")

    service = CaseService(gateway=LlmGateway([Down()], sleep=lambda s: None))
    client = TestClient(create_app(service, TOKENS))
    case = open_case(client, "scenario_f_account_takeover")
    assert case["inquiry"]["outcome"] == "model_unavailable"
    assert case["status"] == "waiting_for_approval"
    assert {"rapid_series", "unknown_device"} <= {f["code"] for f in case["findings"]}


def test_without_a_model_there_is_no_investigation() -> None:
    client = TestClient(create_app(CaseService(), TOKENS))
    case = open_case(client, "scenario_f_account_takeover")
    assert case["inquiry"] is None and case["status"] == "waiting_for_approval"
