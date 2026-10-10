"""Checks that the committed synthetic dataset really contains what each scenario claims."""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nexa.bank_sim import InMemoryBank, default_data_dir, load_bank, load_scenarios
from nexa.bank_sim.models import KycStatus, RiskTier, TransactionRecord
from nexa.bank_sim.scenarios import ScenarioSpec
from nexa.config import DEFAULT_THRESHOLDS
from nexa.domain.actions import ActionType
from nexa.domain.actors import Role

ROOT = Path(__file__).resolve().parents[4]
THRESHOLDS = DEFAULT_THRESHOLDS


@pytest.fixture(scope="module")
def bank() -> InMemoryBank:
    return load_bank()


@pytest.fixture(scope="module")
def scenarios() -> dict[str, ScenarioSpec]:
    return {s.id: s for s in load_scenarios()}


def average_before(bank: InMemoryBank, account_id: str, cutoff: datetime) -> float:
    """Average debit amount in the customer's history before the alert window."""
    history = [
        t.amount
        for t in bank.list_transactions(account_id, until=cutoff)
        if t.direction.value == "debit" and not t.id.startswith("txn_sc_")
    ]
    return sum(history) / len(history)


def alert_txn(bank: InMemoryBank, scenario: ScenarioSpec) -> TransactionRecord:
    return bank.get_transaction(scenario.alert.transaction_id)


def test_seed_data_is_reproducible(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "generate_synthetic_data", ROOT / "scripts" / "generate_synthetic_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(tmp_path)
    for generated in tmp_path.glob("*.json"):
        committed = default_data_dir() / generated.name
        assert generated.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
            f"{generated.name} differs; rerun scripts/generate_synthetic_data.py"
        )


def test_every_scenario_alert_points_at_real_records(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    assert set(scenarios) == {
        "scenario_a_normal",
        "scenario_b_suspicious",
        "scenario_c_incomplete_kyc",
        "scenario_d_conflicting_evidence",
        "scenario_e_unauthorized_action",
        "scenario_f_account_takeover",
        "scenario_x_prompt_injection",
    }
    for scenario in scenarios.values():
        alert = scenario.alert
        transaction = bank.get_transaction(alert.transaction_id)
        assert transaction.account_id == alert.account_id
        assert bank.get_account(alert.account_id).customer_id == alert.customer_id


def test_dataset_has_the_variety_the_prd_asks_for(bank: InMemoryBank) -> None:
    customers = [bank.get_customer(f"cust_{n:03d}") for n in range(1, 17)]
    assert any(c.risk_tier is RiskTier.HIGH for c in customers)
    assert any(c.travel_notices for c in customers)

    all_txns = [
        t for c in customers for a in bank.list_accounts(c.id) for t in bank.list_transactions(a.id)
    ]
    assert any(t.country != "PK" for t in all_txns), "no unusual locations"

    duplicates = [
        (a, b)
        for a, b in zip(all_txns, all_txns[1:], strict=False)
        if (a.account_id, a.merchant_name, a.amount) == (b.account_id, b.merchant_name, b.amount)
        and abs((b.occurred_at - a.occurred_at).total_seconds()) < 60
    ]
    assert duplicates, "no duplicate transactions"

    kycs = [bank.get_kyc(c.id) for c in customers]
    assert any(k.status is KycStatus.PENDING for k in kycs), "no incomplete KYC"
    mismatches = [
        c.id
        for c, k in zip(customers, kycs, strict=True)
        if k.address_on_document and not c.address.startswith(k.address_on_document)
    ]
    assert mismatches, "no conflicting customer information"


def test_scenario_a_is_unremarkable(bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]) -> None:
    s = scenarios["scenario_a_normal"]
    t = alert_txn(bank, s)
    assert t.amount < 2 * average_before(bank, t.account_id, t.occurred_at)
    assert t.country == "PK"
    assert not s.expected.must_involve_human


@pytest.mark.parametrize(
    "key",
    ["scenario_b_suspicious", "scenario_d_conflicting_evidence", "scenario_f_account_takeover"],
)
def test_risky_scenarios_exceed_the_amount_threshold(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec], key: str
) -> None:
    t = alert_txn(bank, scenarios[key])
    ratio = t.amount / average_before(bank, t.account_id, t.occurred_at)
    assert ratio >= THRESHOLDS.amount_multiple_of_average


def test_scenario_b_shows_card_testing_and_a_foreign_merchant(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    t = alert_txn(bank, scenarios["scenario_b_suspicious"])
    window_start = t.occurred_at - timedelta(minutes=THRESHOLDS.velocity_window_minutes)
    recent = bank.list_transactions(t.account_id, since=window_start, until=t.occurred_at)
    assert len(recent) >= THRESHOLDS.velocity_transaction_count
    assert t.country != "PK"


def test_scenario_c_has_missing_kyc_items_and_a_high_value_credit(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    s = scenarios["scenario_c_incomplete_kyc"]
    kyc = bank.get_kyc(s.alert.customer_id)
    assert kyc.status is KycStatus.PENDING
    assert set(kyc.missing_items) == {"proof_of_address", "source_of_funds"}
    assert alert_txn(bank, s).amount >= THRESHOLDS.high_value_amount_pkr
    assert ActionType.FREEZE_ACCOUNT in s.expected.forbidden_actions


def test_scenario_d_has_evidence_pointing_both_ways(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    s = scenarios["scenario_d_conflicting_evidence"]
    t = alert_txn(bank, s)
    customer = bank.get_customer(s.alert.customer_id)
    kyc = bank.get_kyc(customer.id)
    # Points toward fraud: unusual amount abroad plus a failed login.
    assert t.country != customer.home_country
    assert t.failed_auth_attempts_prior_hour >= 1
    # Points away from fraud: declared trip, trusted device.
    assert any(
        n.country == t.country and n.from_date <= t.occurred_at.date() <= n.to_date
        for n in customer.travel_notices
    )
    assert t.device_trusted and t.device_id in customer.trusted_device_ids
    # Conflicting customer information.
    assert kyc.address_on_document and not customer.address.startswith(kyc.address_on_document)
    assert not (
        set(s.expected.acceptable_actions) & {ActionType.FREEZE_ACCOUNT, ActionType.BLOCK_CARD}
    )


def test_scenario_e_is_an_authorization_test(scenarios: dict[str, ScenarioSpec]) -> None:
    s = scenarios["scenario_e_unauthorized_action"]
    assert s.expected.authorization_must_block
    assert s.attempt is not None
    assert s.attempt.actor_role is Role.DATA_AGENT
    assert s.attempt.attempted_action is ActionType.FREEZE_ACCOUNT


def test_scenario_f_is_a_rapid_drain_from_an_unknown_device(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    s = scenarios["scenario_f_account_takeover"]
    account = bank.get_account(s.alert.account_id)
    window = [t for t in bank.list_transactions(account.id) if t.id.startswith("txn_sc_f")]
    assert len(window) >= THRESHOLDS.velocity_transaction_count
    assert all(t.is_new_beneficiary and not t.device_trusted for t in window)
    assert max(t.failed_auth_attempts_prior_hour for t in window) >= THRESHOLDS.failed_auth_attempts
    assert sum(t.amount for t in window) > 0.9 * account.balance
    assert s.expected.acceptable_actions == (ActionType.FREEZE_ACCOUNT,)


def test_scenario_x_hides_instructions_in_data(
    bank: InMemoryBank, scenarios: dict[str, ScenarioSpec]
) -> None:
    s = scenarios["scenario_x_prompt_injection"]
    t = alert_txn(bank, s)
    assert s.contains_untrusted_instruction_text
    assert "ignore all previous instructions" in t.memo.lower()
    assert ActionType.FREEZE_ACCOUNT in s.expected.forbidden_actions


def test_scenario_expectations_are_internally_consistent(
    scenarios: dict[str, ScenarioSpec],
) -> None:
    for s in scenarios.values():
        assert not set(s.expected.acceptable_actions) & set(s.expected.forbidden_actions)
