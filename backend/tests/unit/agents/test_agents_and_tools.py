"""Agents get exactly the access their role has, and nothing the model says can change it."""

import pytest
from agent_world import World

from nexa.agents import AgentContext, AgentToolError, DataAgent, ToolSession
from nexa.domain.actors import Role


def test_each_agent_is_limited_to_its_own_tools(world: World) -> None:
    case = world.case("scenario_f_account_takeover")
    analysis = ToolSession(world.context(), Role.ANALYSIS_AGENT, case.id)
    with pytest.raises(AgentToolError) as denied:
        analysis.call("get_customer_profile", {"customer_id": "cust_106"})
    assert denied.value.error_code == "role_not_permitted"
    with pytest.raises(AgentToolError):
        ToolSession(world.context(), Role.DATA_AGENT, case.id).call("execute_authorized_action")


def test_an_agent_cannot_read_accounts_outside_its_case(world: World) -> None:
    case = world.case("scenario_f_account_takeover")
    data = ToolSession(world.context(), Role.DATA_AGENT, case.id)
    with pytest.raises(AgentToolError) as denied:
        data.call("get_account_details", {"account_id": "acc_101"})
    assert denied.value.error_code == "out_of_scope"


def test_the_channel_has_no_default_so_trusted_code_must_choose_it(world: World) -> None:
    with pytest.raises(TypeError):
        AgentContext(registry=world.context().registry, clock=lambda: world.tools.clock())  # type: ignore[call-arg]


def test_the_data_agent_records_four_kinds_of_evidence_without_third_party_text(
    world: World,
) -> None:
    case = world.case("scenario_x_prompt_injection")
    dossier = DataAgent(world.context()).gather(case)
    assert {e.kind.value for e in dossier.evidence} == {
        "transaction",
        "customer_profile",
        "account_state",
        "kyc_status",
    }
    blob = " ".join(e.summary + str(e.data) for e in dossier.evidence)
    assert "ACME" not in blob and "freeze" not in blob.lower()
    assert dossier.transaction.memo  # the memo is kept for scanning, never published


def test_every_tool_call_by_an_agent_is_audited(world: World) -> None:
    case = world.case("scenario_a_normal")
    DataAgent(world.context()).gather(case)
    events = [e for e in world.log.events() if e.case_id == case.id]
    assert {e.event_type.value for e in events} == {"tool_called", "tool_completed"}
    assert len(events) == 8 and all(e.actor.role is Role.DATA_AGENT for e in events)
