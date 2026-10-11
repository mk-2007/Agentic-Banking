"""Nothing changes in the bank without a valid approval, and scenario E is refused."""

from datetime import timedelta

import pytest
from conftest import EXECUTOR, Env, agent, human

from nexa.bank_sim import load_scenarios
from nexa.bank_sim.models import AccountStatus, CardStatus
from nexa.domain.actions import ActionType
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.approval import ApprovalRequest, ApprovalVote, Verdict
from nexa.domain.audit import AuditEventType
from nexa.domain.tooling import ToolResult

FREEZE = {"account_id": "acc_106", "action": "freeze_account"}


def execute(env: Env, args: dict[str, str] | None = None, **kw: object) -> ToolResult:
    call = env.call("execute_authorized_action", EXECUTOR, args or FREEZE, **kw)  # type: ignore[arg-type]
    return env.registry.invoke(call)


def assert_untouched(env: Env, account: str = "acc_106") -> None:
    record = env.bank.get_account(account)
    assert record.status is AccountStatus.ACTIVE
    assert record.card_status is CardStatus.ACTIVE


# --- scenario E (PRD 44-E), driven by the scenario data ----------------
def test_scenario_e_unauthorized_attempt_is_blocked_and_recorded(env: Env) -> None:
    scenario = next(s for s in load_scenarios() if s.id == "scenario_e_unauthorized_action")
    attempt = scenario.attempt
    assert attempt is not None
    actor = Actor(kind=ActorKind.AGENT, id="rogue", role=attempt.actor_role)
    approval = env.freeze_approval(account=attempt.account_id, case="case_e")
    call = env.call(
        "execute_authorized_action", actor,
        {"account_id": attempt.account_id, "action": attempt.attempted_action.value},
        case_id="case_e", approval_id=approval,
    )  # fmt: skip
    result = env.registry.invoke(call)
    assert not result.ok and result.error_code == "role_not_permitted"
    assert_untouched(env, attempt.account_id)
    last = env.log.events()[-1]
    assert last.event_type is AuditEventType.TOOL_DENIED and last.actor.id == "rogue"
    assert scenario.expected.authorization_must_block


@pytest.mark.parametrize("role", [Role.FRAUD_ANALYST, Role.RISK_OFFICER, Role.COMPLIANCE_OFFICER])
def test_even_humans_cannot_call_the_execution_tool_directly(env: Env, role: Role) -> None:
    approval = env.freeze_approval()
    call = env.call("execute_authorized_action", human(role), FREEZE, approval_id=approval)
    assert env.registry.invoke(call).error_code == "role_not_permitted"
    assert_untouched(env)


# --- the approval gate in action ---------------------------------------
def test_no_approval_means_no_execution(env: Env) -> None:
    assert execute(env).error_code == "approval_required"
    assert_untouched(env)


def test_unknown_approval_is_refused(env: Env) -> None:
    assert execute(env, approval_id="apr_made_up").error_code == "approval_not_found"
    assert_untouched(env)


def test_valid_approval_freezes_the_account_and_is_audited(env: Env) -> None:
    approval = env.freeze_approval()
    result = execute(env, approval_id=approval)
    assert result.ok
    assert result.output == {
        "account_id": "acc_106", "action": "freeze_account",
        "account_status": "frozen", "card_status": "active",
    }  # fmt: skip
    assert env.bank.get_account("acc_106").status is AccountStatus.FROZEN
    kinds = [e.event_type for e in env.log.events()]
    assert kinds == [
        AuditEventType.TOOL_CALLED,
        AuditEventType.ACTION_EXECUTED,
        AuditEventType.TOOL_COMPLETED,
    ]
    assert env.log.verify() is None


def test_an_approval_cannot_be_replayed(env: Env) -> None:
    approval = env.freeze_approval()
    assert execute(env, approval_id=approval).ok
    again = execute(env, approval_id=approval)
    assert again.error_code == "approval_already_used"
    executed = [e for e in env.log.events() if e.event_type is AuditEventType.ACTION_EXECUTED]
    assert len(executed) == 1


def test_approval_for_one_account_cannot_freeze_another(env: Env) -> None:
    approval = env.freeze_approval(account="acc_106")
    result = execute(
        env, {"account_id": "acc_102", "action": "freeze_account"}, approval_id=approval
    )
    assert result.error_code == "approval_mismatch"
    assert_untouched(env, "acc_102")


def test_approval_for_one_case_cannot_be_used_in_another(env: Env) -> None:
    approval = env.freeze_approval(case="case_f")
    assert execute(env, approval_id=approval, case_id="case_b").error_code == "approval_mismatch"
    assert_untouched(env)


def test_freeze_approval_cannot_be_used_to_block_a_card(env: Env) -> None:
    approval = env.freeze_approval()
    result = execute(env, {"account_id": "acc_106", "action": "block_card"}, approval_id=approval)
    assert result.error_code == "approval_mismatch"
    assert_untouched(env)


def test_level_four_needs_both_approvers(env: Env) -> None:
    approval = env.freeze_approval()
    env.approvals.votes[approval] = env.approvals.votes[approval][:1]  # risk officer never voted
    assert execute(env, approval_id=approval).error_code == "approval_not_approved"
    assert_untouched(env)


def test_one_person_cannot_play_both_roles(env: Env) -> None:
    approval = env.freeze_approval()
    first = env.approvals.votes[approval][0]
    same_person_second_role = ApprovalVote(
        request_id=approval, approver_id=first.approver_id, role=Role.RISK_OFFICER,
        verdict=Verdict.APPROVE, decided_at=first.decided_at + timedelta(minutes=1),
    )  # fmt: skip
    env.approvals.votes[approval] = [first, same_person_second_role]
    assert execute(env, approval_id=approval).error_code == "approval_not_approved"
    assert_untouched(env)


def test_a_rejection_blocks_execution(env: Env) -> None:
    approval = env.freeze_approval()
    env.approvals.votes[approval].append(
        ApprovalVote(
            request_id=approval, approver_id="cat", role=Role.COMPLIANCE_OFFICER,
            verdict=Verdict.REJECT, decided_at=env.now - timedelta(minutes=2),
        )
    )  # fmt: skip
    assert execute(env, approval_id=approval).error_code == "approval_not_approved"
    assert_untouched(env)


def test_an_expired_approval_cannot_execute(env: Env) -> None:
    approval = env.freeze_approval()
    env.now += timedelta(hours=2)
    result = execute(env, approval_id=approval)
    assert result.error_code == "approval_not_approved"
    assert "expired" in (result.error_message or "")
    assert_untouched(env)


def test_only_block_card_and_freeze_are_executable(env: Env) -> None:
    approval = env.freeze_approval()
    result = execute(env, {"account_id": "acc_106", "action": "no_action"}, approval_id=approval)
    assert result.error_code == "unsupported_action"
    assert_untouched(env)


def test_a_single_analyst_approval_is_enough_for_a_card_block(env: Env) -> None:
    request = ApprovalRequest(
        id="apr_card", case_id="case_f", decision_id="dec_2", target_account_id="acc_106",
        action=ActionType.BLOCK_CARD, risk_level=3, required_roles=(Role.FRAUD_ANALYST,),
        requested_at=env.now - timedelta(minutes=10), expires_at=env.now + timedelta(minutes=50),
    )  # fmt: skip
    vote = ApprovalVote(
        request_id="apr_card", approver_id="ana", role=Role.FRAUD_ANALYST,
        verdict=Verdict.APPROVE, decided_at=env.now - timedelta(minutes=1),
    )  # fmt: skip
    env.approvals.add(request, [vote])
    result = execute(env, {"account_id": "acc_106", "action": "block_card"}, approval_id="apr_card")
    assert result.ok
    record = env.bank.get_account("acc_106")
    assert record.card_status is CardStatus.BLOCKED and record.status is AccountStatus.ACTIVE


def test_a_denied_execution_is_audited_as_a_denial(env: Env) -> None:
    execute(env)
    kinds = [e.event_type for e in env.log.events()]
    assert kinds == [AuditEventType.TOOL_CALLED, AuditEventType.TOOL_DENIED]
    assert env.log.events()[-1].detail.startswith("approval_required")


def test_agents_cannot_use_the_executor_role_by_claiming_it(env: Env) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Actor(kind=ActorKind.AGENT, id="sneaky", role=Role.EXECUTION_SERVICE)
    assert agent(Role.DATA_AGENT).role is Role.DATA_AGENT
