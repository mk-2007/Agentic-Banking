"""The specialist agents on the seven scenarios, with and without a model in the policy step."""

import json

import pytest
from harness import (
    ScenarioResult,
    format_report,
    load_expectations,
    refs_in,
    run_all,
    run_scenario,
)

from nexa.bank_sim import load_scenarios
from nexa.llm import LlmGateway, LlmRequest, ScriptedProvider

SCENARIOS = load_scenarios()


def _failures(results: list[ScenarioResult]) -> str:
    return "\n" + format_report([r for r in results if not r.passed])


def test_deterministic_agents_pass_every_scenario() -> None:
    results = run_all()
    assert all(r.passed for r in results), _failures(results)
    assert not any(r.llm_used for r in results)


def test_every_scenario_has_expectations() -> None:
    expectations = load_expectations()
    assert {s.id for s in SCENARIOS} == set(expectations["scenarios"])  # type: ignore[arg-type]


def _picks_every_clause(request: LlmRequest) -> str:
    prompt = "\n".join(m.content for m in request.messages)
    return json.dumps({"applicable_refs": refs_in(prompt)})  # chooses every retrieved clause


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenarios_pass_with_a_model_in_the_policy_step(scenario) -> None:  # type: ignore[no-untyped-def]
    provider = ScriptedProvider(_picks_every_clause)
    gateway = LlmGateway([provider], sleep=lambda s: None)
    result = run_scenario(scenario, load_expectations(), gateway)
    assert result.passed, _failures([result])
    # Free text from the transaction must never be sent to a model, fenced or not.
    prompts = "\n".join(m.content for req in provider.requests for m in req.messages)
    assert "ACME TRADERS" not in prompts
    assert "Ignore all previous instructions" not in prompts
    assert (provider.calls > 0) == result.llm_used  # the model step really ran when claimed
