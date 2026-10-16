"""The case graph: the happy path, every kind of stop, and the state machine's guard."""

import pytest
from agent_world import SCENARIOS, World

from nexa.agents import (
    AgentDataError,
    AgentToolError,
    AnalysisAgent,
    DataAgent,
    IndicatorCode,
    IssueCode,
    PolicyAgent,
    PolicyResult,
    investigate,
)
from nexa.agents.base import AgentContext
from nexa.agents.dossier import Dossier
from nexa.agents.findings import code_of
from nexa.domain.case import Case, CaseStatus
from nexa.domain.decision import UncertaintyFlag
from nexa.domain.errors import InvalidTransitionError
from nexa.domain.evidence import Evidence
from nexa.orchestration import AgentSet, build_case_graph, run_case
from nexa.orchestration.nodes import CaseNodes

S = CaseStatus
HAPPY = (S.CREATED, S.PLANNING, S.EXECUTING, S.VERIFYING, S.DECISION_READY)


# --- stand-ins that fail in one chosen way ------------------------------------------------
class ToolFailingAnalysis(AnalysisAgent):
    def analyze(self, case: Case, dossier: Dossier) -> tuple[Evidence, ...]:
        raise AgentToolError("get_transaction_history", "timeout")


class InconsistentData(DataAgent):
    def gather(self, case: Case) -> Dossier:
        raise AgentDataError("the transaction does not match the alert")


class ForgingAnalysis(AnalysisAgent):
    """Returns a real finding with its numbers altered so it no longer meets the threshold."""

    def analyze(self, case: Case, dossier: Dossier) -> tuple[Evidence, ...]:
        real = super().analyze(case, dossier)
        return tuple(
            e.model_copy(update={"data": {**e.data, "amount": 1}})
            if code_of(e) is IndicatorCode.AMOUNT_ABOVE_AVERAGE
            else e
            for e in real
        )


class NoPolicyFound(PolicyAgent):
    def research(self, case: Case, findings: object) -> PolicyResult:  # type: ignore[override]
        return PolicyResult()


def swapped(ctx: AgentContext, **replacements: object) -> AgentSet:
    standard = AgentSet.from_context(ctx)
    return AgentSet(**{**standard.__dict__, **replacements})


# --- happy path ----------------------------------------------------------------------------
@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_every_scenario_reaches_decision_ready_through_the_allowed_statuses(
    world: World, scenario_id: str
) -> None:
    run = run_case(world.case(scenario_id), world.context())
    assert run.trail == HAPPY
    assert run.case.status is S.DECISION_READY and run.ready_for_decision
    assert run.failure is None and run.investigation is not None
    assert run.investigation.verification.passed


def test_the_case_records_every_piece_of_evidence_once(world: World) -> None:
    run = run_case(world.case("scenario_f_account_takeover"), world.context())
    assert run.investigation is not None
    ids = [e.id for e in run.investigation.all_evidence]
    assert run.case.evidence_ids == tuple(ids) and len(set(ids)) == len(ids)


def test_the_graph_finds_exactly_what_the_straight_line_runner_finds(world: World) -> None:
    case = world.case("scenario_d_conflicting_evidence")
    via_graph = run_case(case, world.context()).investigation
    straight = investigate(case, world.context())
    assert via_graph is not None
    assert [e.id for e in via_graph.all_evidence] == [e.id for e in straight.all_evidence]


def test_uncertainty_flags_reach_the_end_of_the_run(world: World) -> None:
    run = run_case(world.case("scenario_d_conflicting_evidence"), world.context())
    assert run.investigation is not None
    assert run.investigation.verification.uncertainty_flags == (
        UncertaintyFlag.CONFLICTING_EVIDENCE,
    )


def test_a_non_blocking_verification_issue_does_not_stop_the_case(world: World) -> None:
    ctx = world.context()
    run = run_case(
        world.case("scenario_f_account_takeover"),
        ctx,
        agents=swapped(ctx, policy=NoPolicyFound(ctx)),
    )
    assert run.ready_for_decision and run.investigation is not None
    issues = {i.code for i in run.investigation.verification.issues}
    assert issues == {IssueCode.MISSING_POLICY_SUPPORT}  # visible, but not a blocker


# --- every way to stop ------------------------------------------------------------------------
def test_a_refused_tool_ends_in_failed_tool_with_a_code_and_no_investigation(world: World) -> None:
    case = world.case("scenario_a_normal")
    world.scopes.scopes.clear()  # the case is no longer in scope for any tool
    run = run_case(case, world.context())
    assert run.case.status is S.FAILED_TOOL and not run.ready_for_decision
    assert run.trail == (S.CREATED, S.PLANNING, S.EXECUTING, S.WAITING_FOR_TOOL, S.FAILED_TOOL)
    assert run.failure is not None and run.failure.startswith("get_transaction_details:")
    assert run.investigation is None


def test_a_tool_failure_in_a_later_step_stops_there(world: World) -> None:
    ctx = world.context()
    run = run_case(
        world.case("scenario_b_suspicious"),
        ctx,
        agents=swapped(ctx, analysis=ToolFailingAnalysis(ctx)),
    )
    assert run.case.status is S.FAILED_TOOL
    assert run.failure == "get_transaction_history:timeout"
    assert run.investigation is None  # the later agents never ran


def test_inconsistent_records_end_in_failed_tool(world: World) -> None:
    ctx = world.context()
    run = run_case(
        world.case("scenario_a_normal"), ctx, agents=swapped(ctx, data=InconsistentData(ctx))
    )
    assert run.case.status is S.FAILED_TOOL and run.failure == "records_inconsistent"


def test_a_forged_finding_ends_in_failed_validation(world: World) -> None:
    ctx = world.context()
    run = run_case(
        world.case("scenario_b_suspicious"), ctx, agents=swapped(ctx, analysis=ForgingAnalysis(ctx))
    )
    assert run.trail == (S.CREATED, S.PLANNING, S.EXECUTING, S.VERIFYING, S.FAILED_VALIDATION)
    assert run.failure == "validation:unsupported_finding"
    assert run.investigation is not None and not run.investigation.verification.passed


# --- the state machine's own guard -----------------------------------------------------------
def test_a_step_cannot_skip_a_status(world: World) -> None:
    ctx = world.context()
    nodes = CaseNodes(AgentSet.from_context(ctx), ctx.clock)
    executing = world.case("scenario_a_normal").transition_to(S.PLANNING, ctx.clock())
    executing = executing.transition_to(S.EXECUTING, ctx.clock())
    with pytest.raises(InvalidTransitionError):
        nodes.mark_ready({"case": executing})  # executing -> decision_ready is not allowed


def test_only_new_cases_can_be_run(world: World) -> None:
    ctx = world.context()
    started = world.case("scenario_a_normal").transition_to(S.PLANNING, ctx.clock())
    with pytest.raises(ValueError, match="already planning"):
        run_case(started, ctx)


def test_a_compiled_graph_can_be_reused_for_many_cases(world: World) -> None:
    ctx = world.context()
    graph = build_case_graph(ctx)
    statuses = [
        run_case(world.case(sid), ctx, graph=graph).case.status
        for sid in ("scenario_a_normal", "scenario_c_incomplete_kyc")
    ]
    assert statuses == [S.DECISION_READY, S.DECISION_READY]
    assert set(SCENARIOS) >= {"scenario_a_normal", "scenario_c_incomplete_kyc"}
