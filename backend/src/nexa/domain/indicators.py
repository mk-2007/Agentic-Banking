"""The closed vocabulary of findings: which indicators exist and which way each one pushes.

Agents record findings with these codes and the decision layer reads them, so the vocabulary lives
in the domain, below both. A finding is an `Evidence` whose ``data`` carries a ``code`` and a
``signal`` (see `nexa.agents.findings`). Because the codes are a closed set, any layer can check
them exactly, and no unsupported free text can travel between layers.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class Signal(StrEnum):
    """Which way a finding pushes the assessment."""

    RISK = "risk"
    MITIGATING = "mitigating"
    INFO = "info"


class IndicatorCode(StrEnum):
    """Every finding an analysis can produce (thresholds: NB-POL-FRAUD-001 and NB-POL-AML-001)."""

    AMOUNT_ABOVE_AVERAGE = "amount_above_average"
    HIGH_VALUE = "high_value"
    RAPID_SERIES = "rapid_series"
    CARD_TESTING = "card_testing"
    FAILED_AUTH = "failed_auth"
    NEW_BENEFICIARY = "new_beneficiary"
    UNKNOWN_DEVICE = "unknown_device"
    UNUSUAL_GEOGRAPHY = "unusual_geography"
    KYC_NOT_VERIFIED = "kyc_not_verified"
    KYC_ITEM_MISSING = "kyc_item_missing"
    KYC_ADDRESS_MISMATCH = "kyc_address_mismatch"
    KYC_REVIEW_OVERDUE = "kyc_review_overdue"
    INSTRUCTION_TEXT = "instruction_text"
    TRAVEL_NOTICE = "travel_notice"
    TRUSTED_DEVICE = "trusted_device"
    FAMILIAR_MERCHANT = "familiar_merchant"
    WITHIN_NORMAL_RANGE = "within_normal_range"
    INSUFFICIENT_HISTORY = "insufficient_history"


C = IndicatorCode
SIGNAL_OF: Final[Mapping[IndicatorCode, Signal]] = MappingProxyType(
    {
        C.AMOUNT_ABOVE_AVERAGE: Signal.RISK,
        C.HIGH_VALUE: Signal.RISK,
        C.RAPID_SERIES: Signal.RISK,
        C.CARD_TESTING: Signal.RISK,
        C.FAILED_AUTH: Signal.RISK,
        C.NEW_BENEFICIARY: Signal.RISK,
        C.UNKNOWN_DEVICE: Signal.RISK,
        C.UNUSUAL_GEOGRAPHY: Signal.RISK,
        C.KYC_NOT_VERIFIED: Signal.RISK,
        C.KYC_ITEM_MISSING: Signal.RISK,
        C.KYC_ADDRESS_MISMATCH: Signal.RISK,
        C.KYC_REVIEW_OVERDUE: Signal.RISK,
        C.INSTRUCTION_TEXT: Signal.RISK,  # NB-POL-FRAUD-001 section 6
        C.TRAVEL_NOTICE: Signal.MITIGATING,
        C.TRUSTED_DEVICE: Signal.MITIGATING,
        C.FAMILIAR_MERCHANT: Signal.MITIGATING,
        C.WITHIN_NORMAL_RANGE: Signal.INFO,
        C.INSUFFICIENT_HISTORY: Signal.INFO,
    }
)
