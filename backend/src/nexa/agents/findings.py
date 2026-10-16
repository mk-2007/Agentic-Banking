"""The closed vocabulary of findings, and how a finding is stored as `Evidence`.

Agents hand each other typed facts, not prose. A finding is an `Evidence` object of kind
``BEHAVIOUR_PATTERN`` whose ``data`` carries a machine-readable ``code`` from `IndicatorCode`, its
``signal`` (does it raise or lower concern) and the ids of the evidence it was derived from.
Because the codes are a closed set, a later layer can check them exactly, and no unsupported free
text can travel between agents.
"""

from datetime import datetime

from nexa.domain.base import FlatDict
from nexa.domain.evidence import Evidence, EvidenceKind, SourceRef
from nexa.domain.indicators import SIGNAL_OF, IndicatorCode, Signal

__all__ = [
    "SIGNAL_OF",
    "IndicatorCode",
    "Signal",
    "code_of",
    "derived_from",
    "finding_evidence",
    "is_finding",
    "signal_of",
]


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
