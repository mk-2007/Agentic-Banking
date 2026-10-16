"""A case saved mid-run must come back exactly as it went in, and unknown types must be refused."""

import dataclasses
import logging

import pytest
from agent_world import World
from langgraph.checkpoint.memory import MemorySaver

from nexa.domain.case import CaseStatus
from nexa.orchestration import ALLOWED_TYPES, build_case_graph, checkpoint_serde, run_case

SERDE_LOGGER = "langgraph.checkpoint.serde.jsonplus"


def test_a_whole_case_round_trips_through_a_checkpointer_with_types_intact(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = world.context()
    graph = build_case_graph(ctx, checkpointer=MemorySaver(serde=checkpoint_serde()))
    case = world.case("scenario_d_conflicting_evidence")
    with caplog.at_level(logging.WARNING, logger=SERDE_LOGGER):
        run = run_case(case, ctx, graph=graph, thread_id="t1")
        saved = graph.get_state({"configurable": {"thread_id": "t1"}}).values
    assert not [r for r in caplog.records if "Blocked" in r.getMessage()]  # nothing was refused
    assert run.investigation is not None
    assert saved["case"] == run.case and saved["case"].status is CaseStatus.DECISION_READY
    assert saved["policy"] == run.investigation.policy
    assert saved["verification"] == run.investigation.verification
    assert saved["dossier"] == run.investigation.dossier
    assert tuple(saved["findings"]) == run.investigation.findings
    assert saved["trail"] == list(run.trail)
    assert isinstance(saved["policy"].evidence, tuple)  # tuples inside contracts stay tuples


def test_a_type_that_is_not_on_the_list_is_refused_not_rebuilt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @dataclasses.dataclass
    class NotOnTheList:
        value: int

    serde = checkpoint_serde()
    with caplog.at_level(logging.WARNING, logger=SERDE_LOGGER):
        restored = serde.loads_typed(serde.dumps_typed({"x": NotOnTheList(1)}))
    assert restored == {"x": {"value": 1}}  # plain data, not an instance
    assert any("Blocked" in r.getMessage() for r in caplog.records)


def test_the_allowlist_names_only_our_own_types() -> None:
    assert all(module.startswith("nexa.") for module, _ in ALLOWED_TYPES)
