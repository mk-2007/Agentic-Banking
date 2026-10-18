"""Verification agent: checks the other agents' work before anyone decides on it.

An agent must not simply trust another agent's output (PRD section 10.5). This one is plain code
and re-derives what it can: every finding must cite evidence that exists, carry a signal that
matches its code, and still satisfy its threshold when recomputed from the numbers it recorded.
It also turns the state of the evidence into the `UncertaintyFlag`s a `Decision` must respect:
thin history or missing records mean *insufficient* evidence, and risk findings alongside
mitigating ones mean *conflicting* evidence.
"""

from collections.abc import Sequence
from enum import StrEnum

from nexa.config import FraudThresholds
from nexa.domain.base import Contract
from nexa.domain.case import Case
from nexa.domain.decision import UncertaintyFlag
from nexa.domain.evidence import Evidence, EvidenceKind

from .dossier import Dossier
from .findings import SIGNAL_OF, IndicatorCode, Signal, code_of, derived_from, is_finding, signal_of
from .policy_agent import PolicyResult

REQUIRED_KINDS = (
    EvidenceKind.TRANSACTION,
    EvidenceKind.CUSTOMER_PROFILE,
    EvidenceKind.ACCOUNT_STATE,
    EvidenceKind.KYC_STATUS,
)


class IssueCode(StrEnum):
    """What a verification can object to."""

    MISSING_EVIDENCE = "missing_evidence"
    WRONG_CASE = "wrong_case"
    DANGLING_REFERENCE = "dangling_reference"
    UNSUPPORTED_FINDING = "unsupported_finding"
    BAD_POLICY_REFERENCE = "bad_policy_reference"
    MISSING_POLICY_SUPPORT = "missing_policy_support"


# These stop the case from moving on; the others are reported but do not block.
BLOCKING = frozenset(
    {
        IssueCode.MISSING_EVIDENCE,
        IssueCode.WRONG_CASE,
        IssueCode.DANGLING_REFERENCE,
        IssueCode.UNSUPPORTED_FINDING,
    }
)


class VerificationIssue(Contract):
    """One problem found."""

    code: IssueCode
    message: str
    evidence_id: str | None = None


class VerificationReport(Contract):
    """The verdict on a case's evidence."""

    passed: bool
    issues: tuple[VerificationIssue, ...] = ()
    uncertainty_flags: tuple[UncertaintyFlag, ...] = ()
    missing_kinds: tuple[EvidenceKind, ...] = ()


def _number(evidence: Evidence, key: str) -> float | None:
    value = evidence.data.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def is_supported(evidence: Evidence, t: FraudThresholds) -> bool:
    """Recompute a finding's threshold from the numbers it recorded."""
    code = code_of(evidence)
    if code is None or signal_of(evidence) is not SIGNAL_OF[code]:
        return False
    amount = _number(evidence, "amount")
    match code:
        case IndicatorCode.AMOUNT_ABOVE_AVERAGE:
            average = _number(evidence, "baseline_average")
            return (
                amount is not None and average is not None
                and amount >= t.amount_multiple_of_average * average
            )  # fmt: skip
        case IndicatorCode.HIGH_VALUE:
            return amount is not None and amount >= t.high_value_amount_pkr
        case IndicatorCode.FAILED_AUTH:
            worst = _number(evidence, "max_failed_attempts")
            return worst is not None and worst >= t.failed_auth_attempts
        case IndicatorCode.RAPID_SERIES:
            payments = _number(evidence, "payments")
            return payments is not None and payments >= t.velocity_transaction_count
        case IndicatorCode.CARD_TESTING:
            small = _number(evidence, "small_payments")
            largest = _number(evidence, "max_small_amount")
            alert = _number(evidence, "alert_amount")
            return (
                small is not None and small >= t.card_testing_min_payments
                and largest is not None and alert is not None
                and largest <= alert * t.card_testing_max_fraction_of_alert
            )  # fmt: skip
        case IndicatorCode.INSUFFICIENT_HISTORY:
            seen = _number(evidence, "transactions_in_lookback")
            return seen is not None and seen < t.min_history_transactions
        case IndicatorCode.POSSIBLE_STRUCTURING:
            count = _number(evidence, "qualifying_payments")
            lowest = _number(evidence, "lowest_amount")
            highest = _number(evidence, "highest_amount")
            return (
                count is not None and count >= t.structuring_min_payments
                and lowest is not None and highest is not None
                and lowest >= t.structuring_band_floor * t.high_value_amount_pkr
                and highest < t.high_value_amount_pkr
            )  # fmt: skip
        case _:
            return True


class VerificationAgent:
    """Validates evidence and reports how certain the case is."""

    def __init__(self, thresholds: FraudThresholds) -> None:
        self._thresholds = thresholds

    def verify(
        self,
        case: Case,
        dossier: Dossier,
        findings: Sequence[Evidence],
        policy: PolicyResult,
    ) -> VerificationReport:
        """Check ``dossier``, ``findings`` and ``policy`` for ``case``."""
        issues: list[VerificationIssue] = []
        everything = (*dossier.evidence, *findings, *policy.evidence)
        known = {e.id for e in everything}

        for e in everything:
            if e.case_id != case.id:
                issues.append(VerificationIssue(
                    code=IssueCode.WRONG_CASE, message="evidence belongs to another case",
                    evidence_id=e.id,
                ))  # fmt: skip
        present = {e.kind for e in dossier.evidence}
        missing = tuple(k for k in REQUIRED_KINDS if k not in present)
        for kind in missing:
            issues.append(VerificationIssue(
                code=IssueCode.MISSING_EVIDENCE, message=f"no {kind.value} evidence was gathered",
            ))  # fmt: skip

        for e in findings:
            if not is_finding(e) or not is_supported(e, self._thresholds):
                issues.append(VerificationIssue(
                    code=IssueCode.UNSUPPORTED_FINDING,
                    message="the finding does not hold when recomputed from its own numbers",
                    evidence_id=e.id,
                ))  # fmt: skip
            for source_id in derived_from(e):
                if source_id not in known:
                    issues.append(VerificationIssue(
                        code=IssueCode.DANGLING_REFERENCE,
                        message=f"cites evidence {source_id}, which does not exist",
                        evidence_id=e.id,
                    ))  # fmt: skip
        for e in policy.evidence:
            if e.source.policy is None or not e.source.policy.version:
                issues.append(VerificationIssue(
                    code=IssueCode.BAD_POLICY_REFERENCE,
                    message="a policy clause must name its document version", evidence_id=e.id,
                ))  # fmt: skip

        signals = {signal_of(e) for e in findings}
        codes = {code_of(e) for e in findings}
        flags: list[UncertaintyFlag] = []
        if missing or IndicatorCode.INSUFFICIENT_HISTORY in codes:
            flags.append(UncertaintyFlag.INSUFFICIENT_EVIDENCE)
        if Signal.RISK in signals and Signal.MITIGATING in signals:
            flags.append(UncertaintyFlag.CONFLICTING_EVIDENCE)
        if Signal.RISK in signals and not policy.evidence:
            issues.append(VerificationIssue(
                code=IssueCode.MISSING_POLICY_SUPPORT,
                message="there are risk findings but no policy clause supports acting on them",
            ))  # fmt: skip

        passed = not any(i.code in BLOCKING for i in issues)
        return VerificationReport(
            passed=passed,
            issues=tuple(issues),
            uncertainty_flags=tuple(flags),
            missing_kinds=missing,
        )
