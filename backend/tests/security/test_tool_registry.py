"""Permission matrix, scope, privacy and audit behaviour of the tool layer."""

import pytest
from conftest import EXECUTOR, Env, agent, human

from nexa.config import TOOL_ROLES
from nexa.domain.actors import Role
from nexa.domain.audit import AuditEventType
from nexa.tools import (
    ExecuteAuthorizedAction,
    GetCustomerProfile,
    ToolContext,
    ToolRegistry,
    build_default_registry,
)

READ_TOOL_ARGS: dict[str, dict[str, str | int | float | bool | None]] = {
    "get_customer_profile": {"customer_id": "cust_106"},
    "get_account_details": {"account_id": "acc_106"},
    "get_transaction_details": {"transaction_id": "txn_sc_f1"},
    "get_transaction_history": {"account_id": "acc_106"},
    "get_kyc_status": {"customer_id": "cust_106"},
}


# --- the full role x tool matrix --------------------------------------
@pytest.mark.parametrize("tool", sorted(READ_TOOL_ARGS))
@pytest.mark.parametrize("role", list(Role))
def test_every_role_and_read_tool_combination(env: Env, tool: str, role: Role) -> None:
    actor = agent(role) if not role.is_human and role is not Role.EXECUTION_SERVICE else None
    if role.is_human:
        actor = human(role)
    if role is Role.EXECUTION_SERVICE:
        actor = EXECUTOR
    assert actor is not None
    result = env.registry.invoke(env.call(tool, actor, READ_TOOL_ARGS[tool]))
    if role in TOOL_ROLES[tool]:
        assert result.ok, result.error_code
    else:
        assert not result.ok
        assert result.error_code == "role_not_permitted"


@pytest.mark.parametrize("role", list(Role))
def test_only_the_execution_service_may_call_the_execution_tool(env: Env, role: Role) -> None:
    approval = env.freeze_approval()
    actor = (
        EXECUTOR
        if role is Role.EXECUTION_SERVICE
        else (human(role) if role.is_human else agent(role))
    )
    call = env.call(
        "execute_authorized_action", actor,
        {"account_id": "acc_106", "action": "freeze_account"}, approval_id=approval,
    )  # fmt: skip
    result = env.registry.invoke(call)
    assert result.ok == (role is Role.EXECUTION_SERVICE)
    if role is not Role.EXECUTION_SERVICE:
        assert result.error_code == "role_not_permitted"


def test_unknown_tool_is_denied(env: Env) -> None:
    result = env.registry.invoke(env.call("drop_all_tables", agent(Role.DATA_AGENT)))
    assert result.error_code == "unknown_tool"


def test_agents_must_name_a_case(env: Env) -> None:
    call = env.call(
        "get_account_details", agent(Role.DATA_AGENT), {"account_id": "acc_106"}, case_id=None
    )
    assert env.registry.invoke(call).error_code == "case_required"


# --- case scope --------------------------------------------------------
def test_agent_cannot_read_records_outside_its_case(env: Env) -> None:
    data_agent = agent(Role.DATA_AGENT)
    for tool, args in [
        ("get_account_details", {"account_id": "acc_102"}),
        ("get_customer_profile", {"customer_id": "cust_102"}),
        ("get_transaction_history", {"account_id": "acc_102"}),
        ("get_transaction_details", {"transaction_id": "txn_sc_b5"}),
        ("get_kyc_status", {"customer_id": "cust_102"}),
    ]:
        result = env.registry.invoke(env.call(tool, data_agent, args, case_id="case_f"))
        assert result.error_code == "out_of_scope", tool


def test_unknown_case_is_denied(env: Env) -> None:
    call = env.call(
        "get_account_details", agent(Role.DATA_AGENT), {"account_id": "acc_106"}, case_id="case_zzz"
    )
    assert env.registry.invoke(call).error_code == "out_of_scope"


# --- privacy / data minimisation ---------------------------------------
def test_profile_hides_contact_details_and_masks_the_name(env: Env) -> None:
    result = env.registry.invoke(
        env.call("get_customer_profile", agent(Role.DATA_AGENT), {"customer_id": "cust_106"})
    )
    assert result.ok
    text = str(result.output)
    customer = env.bank.get_customer("cust_106")
    for secret in (customer.phone, customer.email, customer.address, customer.full_name):
        assert secret not in text
    assert result.output["display_name"] == "F. I."


def test_kyc_tool_reports_consistency_without_raw_addresses(env: Env) -> None:
    case_d_actor = human(Role.FRAUD_ANALYST)
    result = env.registry.invoke(
        env.call("get_kyc_status", case_d_actor, {"customer_id": "cust_104"}, case_id=None)
    )
    assert result.ok
    assert result.output["address_matches_customer_record"] is False
    assert "Gulshan" not in str(result.output)


def test_history_omits_memo_and_flags_untrusted_text(env: Env) -> None:
    result = env.registry.invoke(
        env.call("get_transaction_history", agent(Role.ANALYSIS_AGENT), {"account_id": "acc_106"})
    )
    assert result.ok
    rows = result.output["transactions"]
    assert isinstance(rows, list) and rows
    assert all("memo" not in row for row in rows)  # type: ignore[operator]
    assert result.output["untrusted_text_fields"] == ["merchant_name"]


def test_injection_text_is_returned_as_labelled_data(env: Env) -> None:
    from nexa.security import CaseScope

    env.scopes.add(CaseScope(case_id="case_x", customer_id="cust_107", account_ids=("acc_107",)))
    result = env.registry.invoke(
        env.call(
            "get_transaction_details",
            agent(Role.DATA_AGENT),
            {"transaction_id": "txn_sc_x1"},
            case_id="case_x",
        )
    )
    assert result.ok
    assert "ignore all previous instructions" in str(result.output["memo"]).lower()
    assert result.output["untrusted_text_fields"] == ["merchant_name", "memo"]
    assert env.bank.get_account("acc_107").status.value == "active"  # reading it changed nothing


def test_history_limit_truncates_and_says_so(env: Env) -> None:
    human_actor = human(Role.FRAUD_ANALYST)
    result = env.registry.invoke(
        env.call(
            "get_transaction_history",
            human_actor,
            {"account_id": "acc_106", "limit": 3},
            case_id=None,
        )
    )
    assert result.output["returned"] == 3
    assert result.output["truncated"] is True
    assert result.output["total_in_window"] > 3


# --- argument and error handling --------------------------------------
def test_bad_arguments_are_reported_not_crashed(env: Env) -> None:
    result = env.registry.invoke(
        env.call("get_account_details", agent(Role.DATA_AGENT), {"wrong": "x"})
    )
    assert result.error_code == "invalid_arguments"


def test_extra_arguments_are_rejected(env: Env) -> None:
    args = {"account_id": "acc_106", "sneaky": "yes"}
    result = env.registry.invoke(env.call("get_account_details", agent(Role.DATA_AGENT), args))
    assert result.error_code == "invalid_arguments"


def test_missing_record_is_not_found(env: Env) -> None:
    result = env.registry.invoke(
        env.call(
            "get_transaction_details",
            human(Role.FRAUD_ANALYST),
            {"transaction_id": "nope"},
            case_id=None,
        )
    )
    assert result.error_code == "not_found"


def test_a_crashing_tool_returns_an_error_and_is_audited(env: Env) -> None:
    class Broken(GetCustomerProfile):
        def run(self, call, ctx):  # type: ignore[no-untyped-def]
            raise RuntimeError("secret internal detail")

    registry = ToolRegistry(env.ctx)
    registry.register(Broken())
    result = registry.invoke(
        env.call("get_customer_profile", agent(Role.DATA_AGENT), {"customer_id": "cust_106"})
    )
    assert result.error_code == "internal_error"
    assert "secret internal detail" not in str(result)
    assert env.log.events()[-1].detail == "failed: internal_error"


# --- registration rules ------------------------------------------------
def test_registry_rejects_tools_not_in_the_matrix(env: Env) -> None:
    class Rogue(GetCustomerProfile):
        spec = GetCustomerProfile.spec.model_copy(update={"name": "rogue_tool"})

    with pytest.raises(ValueError, match="no entry"):
        env.registry.register(Rogue())


def test_registry_rejects_tools_whose_roles_differ_from_config(env: Env) -> None:
    class Greedy(GetCustomerProfile):
        spec = GetCustomerProfile.spec.model_copy(update={"required_roles": tuple(Role)})

    registry = ToolRegistry(env.ctx)
    with pytest.raises(ValueError, match="differ"):
        registry.register(Greedy())


def test_registry_detects_unregistered_matrix_entries(env: Env) -> None:
    registry = ToolRegistry(env.ctx)
    registry.register(ExecuteAuthorizedAction())
    with pytest.raises(ValueError, match="not registered"):
        registry.assert_complete()


def test_duplicate_registration_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError, match="already registered"):
        env.registry.register(GetCustomerProfile())


def test_default_registry_has_every_tool_in_the_matrix(env: Env) -> None:
    assert set(env.registry.tool_names) == set(TOOL_ROLES)
    assert isinstance(build_default_registry(env.ctx), ToolRegistry)  # type: ignore[attr-defined]
    assert isinstance(env.ctx, ToolContext)  # type: ignore[attr-defined]


# --- audit -------------------------------------------------------------
def test_successful_call_leaves_a_started_and_completed_event(env: Env) -> None:
    env.registry.invoke(
        env.call("get_account_details", agent(Role.DATA_AGENT), {"account_id": "acc_106"})
    )
    events = env.log.events()
    assert [e.event_type for e in events] == [
        AuditEventType.TOOL_CALLED,
        AuditEventType.TOOL_COMPLETED,
    ]
    assert (
        events[0].input_hash and events[1].output_ref and events[1].output_ref.startswith("sha256:")
    )
    assert events[0].case_id == "case_f"
    assert env.log.verify() is None


def test_audit_stores_hashes_not_raw_data(env: Env) -> None:
    env.registry.invoke(
        env.call("get_account_details", agent(Role.DATA_AGENT), {"account_id": "acc_106"})
    )
    dumped = " ".join(e.model_dump_json() for e in env.log.events())
    assert "900000" not in dumped and "acc_106" not in dumped


def test_every_denial_is_audited(env: Env) -> None:
    env.registry.invoke(
        env.call("get_account_details", agent(Role.REPORTING_AGENT), {"account_id": "acc_106"})
    )
    env.registry.invoke(
        env.call("get_account_details", agent(Role.DATA_AGENT), {"account_id": "acc_102"})
    )
    env.registry.invoke(env.call("nonexistent", agent(Role.DATA_AGENT)))
    denied = [e for e in env.log.events() if e.event_type is AuditEventType.TOOL_DENIED]
    assert len(denied) == 3
    assert [e.detail.split(":")[0] for e in denied] == [
        "role_not_permitted",
        "out_of_scope",
        "unknown_tool",
    ]


def test_tools_do_not_mutate_the_bank_when_only_reading(env: Env) -> None:
    before = env.bank.get_account("acc_106")
    for tool, args in READ_TOOL_ARGS.items():
        env.registry.invoke(env.call(tool, human(Role.FRAUD_ANALYST), args, case_id=None))
    assert env.bank.get_account("acc_106") == before
