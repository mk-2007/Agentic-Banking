"""The randomised-traffic runner, end to end through the app path, the monitor and the case graph."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexa.api import CaseService, Principal, create_app
from nexa.api.sim import SimulationRunner, run_simulation
from nexa.domain.actors import Role
from nexa.evaluation import PERSONAS
from nexa.llm import LlmGateway, LlmRequest, ScriptedProvider
from nexa.rag import load_knowledge_base

KNOWLEDGE = load_knowledge_base()


@pytest.fixture(scope="module")
def rules() -> SimulationRunner:
    return SimulationRunner(knowledge=KNOWLEDGE)


# --- with no model: a deterministic baseline that also documents its own blind spot ------------------
def test_there_are_accounts_to_run_on() -> None:
    assert len(SimulationRunner.accounts()) >= 6


def test_honest_customers_are_never_restricted_and_routine_ones_are_left_alone(
    rules: SimulationRunner,
) -> None:
    for seed in (1, 2, 3):
        for persona in ("honest_routine", "honest_big_purchase", "honest_new_payee"):
            r = rules.run_episode(persona, seed, "acc_010")
            assert r.score.safe, (persona, seed, r.score.actions)
        assert not rules.run_episode("honest_routine", seed, "acc_010").score.opened


def test_the_baseline_catches_the_takeover_and_card_testing_for_the_right_reason(
    rules: SimulationRunner,
) -> None:
    take = rules.run_episode("takeover", 1, "acc_010")
    assert take.score.worst == "freeze_account" and take.score.recognised
    assert "rapid_series" in {c for case in take.cases for c in case["findings"]}
    card = rules.run_episode("card_testing", 1, "acc_010")
    assert card.score.worst == "block_card" and card.score.recognised


def test_the_baseline_escalates_structuring_only_by_accident(rules: SimulationRunner) -> None:
    r = rules.run_episode("structuring", 1, "acc_010")
    assert r.score.useful and r.score.opened  # an acceptable outcome...
    assert not r.score.recognised  # ...but nothing ever recognised structuring
    assert not any("possible_structuring" in c["findings"] for c in r.cases)


def test_a_frozen_account_cannot_be_used_after_the_episode_but_the_run_never_votes(
    rules: SimulationRunner,
) -> None:
    r = rules.run_episode("takeover", 2, "acc_010")
    freeze = next(c for c in r.cases if c["action"] == "freeze_account")
    assert freeze["status"] == "waiting_for_approval"  # nobody approved, so nothing was frozen


def test_episodes_do_not_contaminate_each_other(rules: SimulationRunner) -> None:
    first = rules.run_episode("takeover", 4, "acc_010")
    again = rules.run_episode("takeover", 4, "acc_010")
    assert first.score == again.score and len(first.monitor) == len(again.monitor)


def test_a_whole_run_summarises_every_persona(rules: SimulationRunner) -> None:
    out = run_simulation(rules, [1])
    assert [e["persona"] for e in out["episodes"]] == list(PERSONAS)
    s = out["summary"]
    assert s["fraud_episodes"] == 4 and s["fraud_caught"] == 4 and s["honest_restricted"] == 0
    assert s["fraud_recognised"] == 3  # structuring is caught, but not recognised
    assert set(out["labels"]) == set(PERSONAS)


# --- with a model that does its job, structuring is recognised -----------------------------------------
def test_a_model_that_investigates_recognises_structuring() -> None:
    def model(request: LlmRequest) -> str:
        schema = request.messages[0].content
        if "applicable_refs" in schema:
            return json.dumps({"applicable_refs": []})
        if "open_case" in schema:
            return json.dumps({"open_case": True, "reason": "near_threshold_cluster"})
        asked = request.messages[2].content
        if len(request.messages) <= 3:
            account = asked.split("account_id=")[1].split()[0]
            args = {"account_id": account, "since": "2026-07-01", "limit": 500}
            return json.dumps(
                {"action": "call", "lookup": "get_transaction_history", "arguments": args}
            )
        claims = [{"code": "possible_structuring", "cited": ["obs_1"]}]
        return json.dumps({"action": "conclude", "claims": claims})

    gateway = LlmGateway([ScriptedProvider(model)], sleep=lambda s: None)
    runner = SimulationRunner(gateway, knowledge=KNOWLEDGE)
    r = runner.run_episode("structuring", 1, "acc_010")
    assert r.score.recognised and r.score.useful
    added = [c["inquiry"]["added"] for c in r.cases if c["inquiry"]]
    assert ["possible_structuring"] in added  # the model proposed it and code confirmed it
    assert all(m["path"] == "model" for m in r.monitor)  # the model, not the floor, opened these


# --- the saved result is shown to the auditor and nobody else ------------------------------------------
def test_the_auditor_reads_the_saved_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tokens = {
        "t-aud": Principal("audrey", Role.AUDITOR),
        "t-ana": Principal("ana", Role.FRAUD_ANALYST),
    }
    client = TestClient(create_app(CaseService(), tokens))
    h = {"Authorization": "Bearer t-aud"}
    path = tmp_path / "sim.json"
    monkeypatch.setattr("nexa.api.lab.sim_results_path", lambda: path)
    assert client.get("/admin/lab/sim", headers=h).json() == {
        **client.get("/admin/lab/sim", headers=h).json(),
        "available": False,
    }
    out = run_simulation(SimulationRunner(knowledge=KNOWLEDGE), [1], ("honest_routine", "takeover"))
    path.write_text(
        json.dumps(
            {"saved_at": "now", "complete": True, "seeds": [1], "rules": out, "agentic": None}
        )
    )
    got = client.get("/admin/lab/sim", headers=h).json()
    assert got["available"] and got["rules"]["summary"]["episodes"] == 2 and got["agentic"] is None
    assert "Shop" not in json.dumps(got)  # no merchant text in what the lab shows
    assert (
        client.get("/admin/lab/sim", headers={"Authorization": "Bearer t-ana"}).status_code == 403
    )
    assert client.get("/admin/lab/sim").status_code == 401
