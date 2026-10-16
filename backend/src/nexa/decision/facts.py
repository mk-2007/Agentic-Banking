"""Reading findings: the typed facts a decision provider is allowed to see.

A finding is `Evidence` with a ``code`` and ``signal`` from the closed vocabulary. Anything that is
not one of ours (a forged code, a missing signal) is skipped here, so no provider interprets it.
"""

from dataclasses import dataclass

from nexa.domain.evidence import Evidence
from nexa.domain.indicators import IndicatorCode, Signal


@dataclass(frozen=True)
class Facts:
    """The findings of one case, grouped by code and by signal."""

    by_code: dict[IndicatorCode, tuple[Evidence, ...]]
    risk: tuple[Evidence, ...]
    mitigating: tuple[Evidence, ...]
    info: tuple[Evidence, ...]

    def of(self, *codes: IndicatorCode) -> tuple[Evidence, ...]:
        """Return the findings with any of ``codes``."""
        return tuple(e for code in codes for e in self.by_code.get(code, ()))

    @property
    def codes(self) -> frozenset[IndicatorCode]:
        """The codes of every finding in the case."""
        return frozenset(self.by_code)

    def has(self, code: IndicatorCode) -> bool:
        """Return whether a finding with ``code`` exists."""
        return code in self.by_code


def read_facts(findings: tuple[Evidence, ...]) -> Facts:
    """Group ``findings`` by code and signal, skipping anything outside the vocabulary."""
    by_code: dict[IndicatorCode, list[Evidence]] = {}
    risk: list[Evidence] = []
    mitigating: list[Evidence] = []
    info: list[Evidence] = []
    for evidence in findings:
        raw_code, raw_signal = evidence.data.get("code"), evidence.data.get("signal")
        try:
            code = IndicatorCode(raw_code) if isinstance(raw_code, str) else None
            signal = Signal(raw_signal) if isinstance(raw_signal, str) else None
        except ValueError:
            continue  # not one of our findings: ignored, never interpreted
        if code is None or signal is None:
            continue
        by_code.setdefault(code, []).append(evidence)
        {Signal.RISK: risk, Signal.MITIGATING: mitigating, Signal.INFO: info}[signal].append(
            evidence
        )
    return Facts(
        {code: tuple(items) for code, items in by_code.items()},
        tuple(risk),
        tuple(mitigating),
        tuple(info),
    )


def unique_ids(evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    """Return the ids of ``evidence``, without repeats, in order."""
    return tuple(dict.fromkeys(e.id for e in evidence))  # unique, in order
