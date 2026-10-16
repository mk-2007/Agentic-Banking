"""The verification agent must catch what the others got wrong or left out."""

from datetime import date

from agent_builders import ALERT_AT, calm_history, dossier, txn

from nexa.agents import IndicatorCode, IssueCode, PolicyResult, VerificationAgent, derive_findings
from nexa.agents.dossier import KycFact, TravelNoticeFact
from nexa.config import DEFAULT_THRESHOLDS
from nexa.domain.case import Alert, Case
from nexa.domain.decision import UncertaintyFlag
from nexa.domain.evidence import Evidence, EvidenceKind, PolicyRef, SourceRef

T = DEFAULT_THRESHOLDS
CASE = Case(
    id="case_1",
    alert=Alert(id="a", transaction_id="t_alert", account_id="acc_1", customer_id="c1",
                trigger="x", raised_at=ALERT_AT),
    created_at=ALERT_AT, updated_at=ALERT_AT,
)  # fmt: skip


def clause(case_id: str = "case_1", version: str = "1.0") -> Evidence:
    return Evidence(
        id="ev_policy", case_id=case_id, kind=EvidenceKind.POLICY_CLAUSE, summary="p",
        source=SourceRef(policy=PolicyRef(doc_id="NB-POL-FRAUD-001", version=version, section="2")),
        collected_at=ALERT_AT,
    )  # fmt: skip


def policy(*evidence: Evidence) -> PolicyResult:
    return PolicyResult(evidence=evidence)


def verify(alert, history, *, evidence=(), **kwargs):  # type: ignore[no-untyped-def]
    d = dossier(alert, **kwargs)
    findings = derive_findings(d, history, T, ALERT_AT)
    return d, findings, VerificationAgent(T).verify(CASE, d, findings, policy(*evidence))


def test_honest_findings_with_policy_support_pass() -> None:
    alert = txn(amount=9_000, merchant="Somewhere New")
    _, _, report = verify(alert, calm_history(), evidence=(clause(),))
    assert report.passed and not report.issues and not report.uncertainty_flags


def test_a_finding_whose_numbers_do_not_meet_the_threshold_is_rejected() -> None:
    d, findings, _ = verify(txn(amount=9_000), calm_history(), evidence=(clause(),))
    forged = next(f for f in findings if f.data["code"] == IndicatorCode.AMOUNT_ABOVE_AVERAGE)
    tampered = forged.model_copy(update={"data": {**forged.data, "amount": 1_100}})
    report = VerificationAgent(T).verify(CASE, d, [tampered], policy(clause()))
    assert not report.passed
    assert report.issues[0].code is IssueCode.UNSUPPORTED_FINDING


def test_a_finding_that_cites_missing_evidence_is_rejected() -> None:
    d, findings, _ = verify(txn(amount=9_000), calm_history(), evidence=(clause(),))
    orphan = findings[0].model_copy(
        update={"data": {**findings[0].data, "derived_from": "ev_ghost"}}
    )
    report = VerificationAgent(T).verify(CASE, d, [orphan], policy(clause()))
    assert IssueCode.DANGLING_REFERENCE in {i.code for i in report.issues}
    assert not report.passed


def test_evidence_from_another_case_is_rejected() -> None:
    _, _, report = verify(txn(amount=9_000), calm_history(), evidence=(clause(case_id="case_2"),))
    assert IssueCode.WRONG_CASE in {i.code for i in report.issues} and not report.passed


def test_missing_records_block_and_mark_the_evidence_insufficient() -> None:
    d = dossier(txn())
    partial = d.model_copy(update={"evidence": d.evidence[:2]})
    report = VerificationAgent(T).verify(CASE, partial, (), policy())
    assert not report.passed
    assert set(report.missing_kinds) == {EvidenceKind.ACCOUNT_STATE, EvidenceKind.KYC_STATUS}
    assert UncertaintyFlag.INSUFFICIENT_EVIDENCE in report.uncertainty_flags


def test_thin_history_is_insufficient_but_not_a_failure() -> None:
    _, _, report = verify(txn(), calm_history(5))
    assert report.passed
    assert report.uncertainty_flags == (UncertaintyFlag.INSUFFICIENT_EVIDENCE,)


def test_risk_and_mitigating_findings_together_mean_conflicting_evidence() -> None:
    notice = TravelNoticeFact(country="AE", from_date=date(2026, 9, 28), to_date=date(2026, 10, 2))
    kyc = KycFact(customer_id="c1", status="pending")
    _, _, report = verify(
        txn(country="AE"), calm_history(), evidence=(clause(),), kyc=kyc, notices=(notice,)
    )
    assert report.uncertainty_flags == (UncertaintyFlag.CONFLICTING_EVIDENCE,)


def test_risk_without_any_policy_support_is_reported_but_does_not_block() -> None:
    _, _, report = verify(txn(amount=9_000), calm_history())
    assert report.passed
    assert IssueCode.MISSING_POLICY_SUPPORT in {i.code for i in report.issues}
