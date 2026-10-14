"""The closed vocabulary of findings, and how a finding is stored as `Evidence`.

Agents hand each other typed facts, not prose. A finding is an `Evidence` object of kind
``BEHAVIOUR_PATTERN`` whose ``data`` carries a machine-readable ``code`` from `IndicatorCode`, its
``signal`` (does it raise or lower concern) and the ids of the evidence it was derived from.
Because the codes are a closed set, a later layer can check them exactly, and no unsupported free
text can travel between agents.
"""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from nexa.domain.base import FlatDict
from nexa.domain.evidence import Evidence, EvidenceKind, SourceRef


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


def finding_evidence(
    case_id: str,
    code: IndicatorCode,
    summary: str,
    *,
    derived_from: tuple[str, ...],
    source: SourceRef,
    collected_at: datetime,
    values: FlatDict | None = None,
    detail: str | None = None,
) -> Evidence:
    """Build the `Evidence` that records one finding.

    ``detail`` separates findings that share a code (one per missing KYC item). ``summary`` and
    ``values`` must never contain third-party text such as merchant names or memos.
    """
    suffix = f"_{detail}" if detail else ""
    data: FlatDict = {
        "code": code.value,
        "signal": SIGNAL_OF[code].value,
        "derived_from": ",".join(derived_from),
        **(values or {}),
    }
    return Evidence(
        id=f"ev_{case_id}_{code.value}{suffix}",
        case_id=case_id,
        kind=EvidenceKind.BEHAVIOUR_PATTERN,
        summary=summary,
        data=data,
        source=source,
        collected_at=collected_at,
    )


def is_finding(evidence: Evidence) -> bool:
    """Return whether ``evidence`` was produced by `finding_evidence`."""
    return evidence.kind is EvidenceKind.BEHAVIOUR_PATTERN and "code" in evidence.data


def code_of(evidence: Evidence) -> IndicatorCode | None:
    """Return the finding code of ``evidence``, or None if it is not a known finding."""
    raw = evidence.data.get("code")
    try:
        return IndicatorCode(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def signal_of(evidence: Evidence) -> Signal | None:
    """Return the signal recorded on ``evidence``, or None if absent or unknown."""
    raw = evidence.data.get("signal")
    try:
        return Signal(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def derived_from(evidence: Evidence) -> tuple[str, ...]:
    """Return the ids of the evidence a finding was derived from."""
    raw = evidence.data.get("derived_from")
    return tuple(part for part in raw.split(",") if part) if isinstance(raw, str) else ()
