"""Keeps the policy documents, the configuration and the dataset consistent with each other."""

from pathlib import Path

import pytest

from nexa.config import APPROVAL_MATRIX, DEFAULT_THRESHOLDS
from nexa.domain.actions import ActionType

POLICY_DIR = Path(__file__).resolve().parents[4] / "data" / "policies"
REQUIRED_METADATA = {
    "document_id", "title", "department", "document_type", "version",
    "effective_date", "status", "access_level", "product", "jurisdiction",
}  # fmt: skip


def parse(path: Path) -> tuple[dict[str, str], str]:
    """Split a policy file into its front-matter metadata and body."""
    text = path.read_text(encoding="utf-8")
    _, header, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in header.strip().splitlines())
    return meta, body


POLICIES = sorted(POLICY_DIR.glob("*.md"))
BY_ID = {parse(p)[0]["document_id"]: parse(p)[1] for p in POLICIES}


def test_there_are_policy_documents() -> None:
    assert len(POLICIES) >= 3


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_metadata_follows_the_knowledge_base_convention(path: Path) -> None:
    meta, _ = parse(path)
    assert set(meta) >= REQUIRED_METADATA
    assert meta["status"] == "Active"
    assert path.name.startswith(meta["document_id"])


def test_document_ids_are_unique() -> None:
    ids = [parse(p)[0]["document_id"] for p in POLICIES]
    assert len(ids) == len(set(ids))


def test_fraud_policy_states_the_configured_thresholds() -> None:
    body = BY_ID["NB-POL-FRAUD-001"]
    t = DEFAULT_THRESHOLDS
    assert f"{t.amount_multiple_of_average:g} times" in body
    assert f"PKR {t.high_value_amount_pkr:,}" in body
    velocity = f"{t.velocity_transaction_count} or more payments"
    assert f"{velocity} within {t.velocity_window_minutes} minutes" in body
    assert f"{t.failed_auth_attempts} or more failed" in body
    assert f"{t.history_lookback_days} days" in body
    assert f"{t.min_history_transactions} transactions" in body


def test_aml_policy_states_the_configured_thresholds() -> None:
    body = BY_ID["NB-POL-AML-001"]
    assert f"{DEFAULT_THRESHOLDS.kyc_review_max_age_days} days" in body
    assert f"PKR {DEFAULT_THRESHOLDS.high_value_amount_pkr:,}" in body


def test_authorization_policy_matches_the_approval_matrix() -> None:
    rows = {
        line.split("|")[1].strip().lower(): line.lower()
        for line in BY_ID["NB-POL-AUTH-001"].splitlines()
        if line.startswith("| ") and "---" not in line
    }
    expected_label = {
        ActionType.REQUEST_CUSTOMER_VERIFICATION: "request customer verification",
        ActionType.BLOCK_CARD: "block card",
        ActionType.FREEZE_ACCOUNT: "freeze account",
    }
    for action, rule in APPROVAL_MATRIX.items():
        row = rows[expected_label[action]]
        assert f"{rule.expiry_minutes} minutes" in row
        for role in rule.required_roles:
            assert role.value.replace("_", " ") in row
