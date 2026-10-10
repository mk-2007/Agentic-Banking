"""Fraud and KYC thresholds used by analysis and decision logic.

These numbers are *configuration*, not code: a different bank sets different values.
They are mirrored in the synthetic policy documents under ``data/policies/`` and a test
keeps the two in sync, so the policy text and the behaviour cannot drift apart.
"""

from pydantic import Field

from nexa.domain.base import Contract


class FraudThresholds(Contract):
    """Limits that turn raw activity into risk indicators."""

    amount_multiple_of_average: float = Field(
        default=5.0, gt=1.0, description="Flag a payment this many times the customer's average."
    )
    high_value_amount_pkr: int = Field(
        default=300_000, gt=0, description="Flag any single payment at or above this amount."
    )
    velocity_window_minutes: int = Field(default=60, gt=0)
    velocity_transaction_count: int = Field(
        default=5, gt=1, description="Flag this many payments inside the velocity window."
    )
    failed_auth_attempts: int = Field(
        default=3, gt=0, description="Flag this many failed logins in the hour before a payment."
    )
    history_lookback_days: int = Field(default=90, gt=0)
    min_history_transactions: int = Field(
        default=10, gt=0, description="Below this, the history is too thin to judge behaviour."
    )
    kyc_review_max_age_days: int = Field(default=365, gt=0)


DEFAULT_THRESHOLDS = FraudThresholds()
