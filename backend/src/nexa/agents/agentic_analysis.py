"""Analysis with a model in the loop, under a fact-checker.

The investigator proposes findings; this module decides which of them become findings. Two sources
feed the result:

- the **baseline** (`AnalysisAgent`, plain arithmetic over policy thresholds) always runs, so the
  platform is never less careful than before and a failed model costs nothing;
- the **investigator's claims**, each checked against *what it actually looked at*:
  - a claim for a code the baseline also finds from the same observations is **confirmed**;
  - a claim for `possible_structuring`, which the baseline does not search for, becomes a finding
    only if the policy's criteria hold over the observed history (the model proposes a hypothesis,
    code confirms it);
  - anything else is **dropped** and counted: uncited, citing an observation that does not exist, or
    not supported by what the model saw.

So the model can add a finding the arithmetic would never have looked for, but it cannot remove a
finding or invent one, and the report records every agreement and disagreement for evaluation.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from nexa.config import FraudThresholds
from nexa.domain.base import Contract
from nexa.domain.case import Case
from nexa.domain.evidence import Evidence, SourceRef
from nexa.domain.indicators import IndicatorCode, Signal

from .analysis_agent import AnalysisAgent, derive_findings
from .base import AgentContext
from .dossier import Dossier, TransactionFact
from .findings import SIGNAL_OF, code_of, finding_evidence
from .inquiry import DroppedClaim, InquiryOutcome, InquiryReport
from .investigator_agent import Claim, InvestigatorAgent

STRUCTURING = IndicatorCode.POSSIBLE_STRUCTURING


class AnalysisOutcome(Contract):
    """The findings for a case and the report on how they were reached."""

    findings: tuple[Evidence, ...]
    report: InquiryReport


def structuring_finding(
    dossier: Dossier,
    history: Sequence[TransactionFact],
    t: FraudThresholds,
    *,
    collected_at: datetime,
) -> Evidence | None:
    """Return the finding if the policy's structuring criteria hold over ``history``, else None.

    The alerted payment must itself sit just under the high-value line and be one of at least
    ``structuring_min_payments`` such payments, in its direction, inside the window ending with it.
    """
    alert = dossier.transaction
    line = t.high_value_amount_pkr
    floor = t.structuring_band_floor * line
    window_start = alert.occurred_at - timedelta(hours=t.structuring_window_hours)
    rows = {r.transaction_id: r for r in history}
    rows[alert.transaction_id] = alert
    series = [
        r
        for r in rows.values()
        if r.direction == alert.direction
        and window_start <= r.occurred_at <= alert.occurred_at
        and floor <= r.amount < line
    ]
    if len(series) < t.structuring_min_payments or not floor <= alert.amount < line:
        return None
    amounts = [r.amount for r in series]
    return finding_evidence(
        dossier.case_id,
        STRUCTURING,
        f"{len(series)} {alert.direction} payments within {t.structuring_window_hours} hours, each "
        f"between PKR {min(amounts):,} and PKR {max(amounts):,}, just under the PKR {line:,} line",
        derived_from=(dossier.evidence_id_of("transaction"),),
        source=SourceRef(tool_name="get_transaction_history", record_id=alert.transaction_id),
        collected_at=collected_at,
        values={
            "qualifying_payments": len(series),
            "lowest_amount": min(amounts),
            "highest_amount": max(amounts),
            "total_amount": sum(amounts),
            "window_hours": t.structuring_window_hours,
            "origin": "model",
        },
    )


class AgenticAnalysis:
    """Runs the baseline and the investigator, and reconciles them."""

    def __init__(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._baseline = AnalysisAgent(ctx)
        self._investigator = InvestigatorAgent(ctx)

    def analyze(self, case: Case, dossier: Dossier) -> AnalysisOutcome:
        """Return the baseline findings plus any the model found that code confirms."""
        baseline = self._baseline.analyze(case, dossier)
        inquiry = self._investigator.investigate(case, dossier)
        t, now = self._ctx.thresholds, self._ctx.clock()

        # What the claims are checked against: the baseline's own logic over the history the model
        # actually fetched. A claim about a baseline-covered code holds only if the same logic, run
        # on only what the model saw, also finds it.
        history = tuple(inquiry.history.values())
        seen = {code_of(e) for e in derive_findings(dossier, history, t, now)}
        claims = tuple({c.code: c for c in inquiry.claims}.values())  # one claim per code
        confirmed: list[str] = []
        added: list[Evidence] = []
        dropped: list[DroppedClaim] = []
        for claim in claims:
            reason = self._refusal(claim, frozenset(inquiry.observation_ids))
            if reason is None and claim.code is STRUCTURING:
                found = structuring_finding(dossier, history, t, collected_at=now)
                if found is None:
                    reason = "unsupported"
                else:
                    added.append(found)
            elif reason is None and claim.code in seen:
                confirmed.append(claim.code.value)
            elif reason is None:
                reason = "unsupported"
            if reason is not None:
                dropped.append(DroppedClaim(code=claim.code.value, reason=reason))

        claimed = tuple(c.code.value for c in claims)
        risk_baseline = {
            code.value
            for e in baseline
            if (code := code_of(e)) is not None and SIGNAL_OF[code] is Signal.RISK
        }
        concluded = inquiry.outcome is InquiryOutcome.CONCLUDED
        missed = tuple(sorted(risk_baseline - set(claimed))) if concluded else ()
        report = InquiryReport(
            outcome=inquiry.outcome,
            trace=tuple(inquiry.trace),
            claimed=claimed,
            confirmed=tuple(confirmed),
            added=tuple(STRUCTURING.value for _ in added),
            dropped=tuple(dropped),
            missed=missed,
            tokens=inquiry.tokens,
            repairs=inquiry.repairs,
            provider=inquiry.provider,
        )
        return AnalysisOutcome(findings=(*baseline, *added), report=report)

    @staticmethod
    def _refusal(claim: Claim, observation_ids: frozenset[str]) -> str | None:
        if not claim.cited:
            return "uncited"
        if any(cited not in observation_ids for cited in claim.cited):
            return "unknown_observation"
        return None
