"""The evaluation lab: run the platform on labelled synthetic cases and report how it did.

The lab has its own `CaseService` over its own bank (the core data plus the lab cohort), so lab
runs never appear among, or change, the live cases. The answer key (each case's label) is read
here and never reaches an agent. Responses follow the API's rule: statuses, codes, ids and our own
summaries, never merchant names or memos (third-party text).

Nothing here decides anything. It runs the same graph the live desk uses, stops where the live
desk would wait for votes, and scores the recommendation with `nexa.evaluation`.
"""

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from nexa.bank_sim import (
    InMemoryBank,
    RecordNotFoundError,
    default_data_dir,
    load_lab_bank,
    load_lab_cases,
    load_scenarios,
)
from nexa.bank_sim.models import AccountRecord
from nexa.bank_sim.scenarios import ScenarioSpec
from nexa.domain.clock import Clock, utc_now
from nexa.evaluation import (
    CaseScore,
    Scorecard,
    run_baselines,
    run_hostile,
    score_case,
    scorecard,
)
from nexa.orchestration import CaseRun

from .schemas import AuditEventView, CaseView, Request, view_of
from .service import CaseService

# The core scenarios join the lab under these archetype names (E is an authorization test with no
# recommendation to score, so it stays in the evaluation scripts).
CORE_ARCHETYPES = {
    "scenario_a_normal": "normal",
    "scenario_b_suspicious": "card_testing",
    "scenario_c_incomplete_kyc": "incomplete_kyc",
    "scenario_d_conflicting_evidence": "conflicting_evidence",
    "scenario_f_account_takeover": "account_takeover",
    "scenario_x_prompt_injection": "prompt_injection",
    "scenario_g_legitimate_traveller": "legit_traveller",
    "scenario_h_thin_history": "thin_history",
    "scenario_i_structuring": "structured_deposits",
    "scenario_j_new_phone": "new_phone",
}


class LabRunRequest(Request):
    """Which cases to run: all by default, or some ids, or one archetype."""

    ids: list[str] | None = Field(default=None, max_length=200)
    archetype: str | None = Field(default=None, max_length=60)


class CheckView(BaseModel):
    """One pass/fail check on a case."""

    name: str
    ok: bool
    detail: str


class ScoreView(BaseModel):
    """How a case was handled and whether that was right."""

    action: str | None
    risk_level: int | None
    approval_required: bool
    human_involved: bool
    gate: str | None
    provider: str | None
    finding_codes: list[str]
    flags: list[str]
    checks: list[CheckView]
    useful: bool
    preferred: bool
    over_escalated: bool
    safe: bool
    passed: bool
    duration_ms: float


class ExpectedView(BaseModel):
    """The label: what correct handling looks like."""

    acceptable_actions: list[str]
    forbidden_actions: list[str]
    must_involve_human: bool


class LabCaseRow(BaseModel):
    """One lab case, with its latest score if it has been run."""

    id: str
    archetype: str
    title: str
    description: str
    account_id: str
    customer_id: str
    expected: ExpectedView
    score: ScoreView | None


class ArchetypeView(BaseModel):
    """Results for one kind of case."""

    archetype: str
    total: int
    passed: int
    safe: int
    useful: int


class ScorecardView(BaseModel):
    """Headline numbers over the cases run so far."""

    cases_in_lab: int
    run: int
    passed: int
    safe: int
    useful: int
    human_routed: int
    preferred: int
    over_escalated: int
    unjustified: int
    by_archetype: list[ArchetypeView]
    failed_case_ids: list[str]
    average_ms: float


class LabRunView(BaseModel):
    """The scorecard and every case row after a run."""

    scorecard: ScorecardView
    cases: list[LabCaseRow]


class TransactionView(BaseModel):
    """A transaction without its free text (no merchant name, no memo)."""

    id: str
    occurred_at: str
    direction: str
    amount: int
    country: str
    channel: str
    device_trusted: bool
    is_new_beneficiary: bool
    failed_auth_attempts: int
    is_alert: bool


class AccountProfile(BaseModel):
    """What the bank holds about one account, safe to show."""

    account_id: str
    customer_id: str
    name: str
    city: str
    home_country: str
    risk_tier: str
    product: str
    status: str
    card_status: str
    balance: int
    travel_notices: list[str]
    kyc_status: str
    kyc_missing: list[str]
    address_on_file: str
    address_on_document: str | None
    payments: int
    average_debit: int
    countries: list[str]
    recent: list[TransactionView]


class AccountRow(BaseModel):
    """One line in the account browser."""

    account_id: str
    customer_id: str
    name: str
    city: str
    risk_tier: str
    balance: int
    status: str
    archetype: str | None
    case_id: str | None


class LabReport(BaseModel):
    """Everything about one case: the label, the run, the audit chain and the account."""

    case: LabCaseRow
    run: CaseView | None
    audit: list[AuditEventView]
    account: AccountProfile


class CardView(BaseModel):
    """Headline numbers for one decision maker over the lab cases."""

    total: int
    passed: int
    safe: int
    useful: int
    preferred: int
    over_escalated: int
    human_routed: int
    unjustified: int


class BaselineRow(BaseModel):
    """One decision maker (the agents or a simple rule) on the same cases."""

    key: str
    title: str
    description: str
    card: CardView


class HostileRow(BaseModel):
    """One misbehaving stand-in model behind the real gates."""

    key: str
    title: str
    description: str
    total: int
    raw_unsafe: int
    safe: int
    useful: int
    gate_interventions: int
    fallbacks: int


class LiveCaseView(BaseModel):
    """One case from a saved live-model run."""

    case_id: str
    archetype: str
    rules_action: str
    llm_action: str
    agree: bool
    gate: str | None
    fell_back: bool
    safe: bool
    useful: bool
    preferred: bool


class LiveView(BaseModel):
    """A saved run of a real model against the rules (see scripts/run_lab_live.py)."""

    available: bool
    provider: str = ""
    saved_at: str = ""
    total: int = 0
    agree: int = 0
    safe: int = 0
    useful: int = 0
    preferred: int = 0
    gate_interventions: int = 0
    fallbacks: int = 0
    seconds: float = 0.0
    cases: list[LiveCaseView] = []


def live_results_path() -> Path:
    """Where the latest live-model comparison is saved: ``data/lab_results/live.json``."""
    return default_data_dir().parent / "lab_results" / "live.json"


class UnknownLabCaseError(LookupError):
    """No lab case or account has this id."""


@dataclass
class _Result:
    score: CaseScore
    run: CaseRun
    millis: float


def _score_view(result: _Result) -> ScoreView:
    s = result.score
    return ScoreView(
        action=s.action,
        risk_level=s.risk_level,
        approval_required=s.approval_required,
        human_involved=s.human_involved,
        gate=s.gate,
        provider=s.provider,
        finding_codes=list(s.finding_codes),
        flags=list(s.flags),
        checks=[CheckView(name=c.name, ok=c.ok, detail=c.detail) for c in s.checks],
        useful=s.useful,
        preferred=s.preferred,
        over_escalated=s.over_escalated,
        safe=s.safe,
        passed=s.passed,
        duration_ms=round(result.millis, 1),
    )


class LabService:
    """Runs labelled cases through a private copy of the platform and scores them."""

    def __init__(self, *, clock: Clock = utc_now) -> None:
        self._bank: InMemoryBank = load_lab_bank()
        self._service = CaseService(bank=self._bank, clock=clock)
        core = ((s, CORE_ARCHETYPES[s.id]) for s in load_scenarios() if s.id in CORE_ARCHETYPES)
        lab = ((c, c.archetype) for c in load_lab_cases())
        self._specs: dict[str, tuple[ScenarioSpec, str]] = {s.id: (s, a) for s, a in (*core, *lab)}
        self._results: dict[str, _Result] = {}
        self._clock = clock
        self._lock = threading.RLock()  # run() reads the scorecard while holding it

    # --- cases -----------------------------------------------------------------------------
    def _row(self, spec: ScenarioSpec, archetype: str) -> LabCaseRow:
        result = self._results.get(spec.id)
        e = spec.expected
        return LabCaseRow(
            id=spec.id,
            archetype=archetype,
            title=spec.title,
            description=spec.description,
            account_id=spec.alert.account_id,
            customer_id=spec.alert.customer_id,
            expected=ExpectedView(
                acceptable_actions=[a.value for a in e.acceptable_actions],
                forbidden_actions=[a.value for a in e.forbidden_actions],
                must_involve_human=e.must_involve_human,
            ),
            score=_score_view(result) if result else None,
        )

    def cases(self) -> list[LabCaseRow]:
        """Every lab case with its latest score, in archetype order."""
        with self._lock:
            return [self._row(s, a) for s, a in self._specs.values()]

    def run(self, ids: list[str] | None = None, archetype: str | None = None) -> LabRunView:
        """Run the chosen cases (all by default) and return the updated scorecard."""
        with self._lock:
            chosen = [
                spec_id
                for spec_id, (_, arch) in self._specs.items()
                if (ids is None or spec_id in ids) and (archetype is None or arch == archetype)
            ]
            unknown = set(ids or ()) - set(self._specs)
            if unknown:
                raise UnknownLabCaseError(", ".join(sorted(unknown)))
            for spec_id in chosen:
                spec, arch = self._specs[spec_id]
                a = spec.alert
                started = time.perf_counter()
                run = self._service.open_case(
                    account_id=a.account_id,
                    customer_id=a.customer_id,
                    transaction_id=a.transaction_id,
                    trigger=a.trigger,
                )
                millis = (time.perf_counter() - started) * 1000
                self._results[spec_id] = _Result(score_case(spec, arch, run), run, millis)
        return LabRunView(scorecard=self.scorecard(), cases=self.cases())

    def scorecard(self) -> ScorecardView:
        """Headline numbers over the cases run so far."""
        with self._lock:
            done = list(self._results.values())
            card = scorecard([r.score for r in done])
            return ScorecardView(
                cases_in_lab=len(self._specs),
                run=card.total,
                passed=card.passed,
                safe=card.safe,
                useful=card.useful,
                human_routed=card.human_routed,
                preferred=card.preferred,
                over_escalated=card.over_escalated,
                unjustified=card.unjustified,
                by_archetype=[
                    ArchetypeView(
                        archetype=t.archetype,
                        total=t.total,
                        passed=t.passed,
                        safe=t.safe,
                        useful=t.useful,
                    )
                    for t in card.by_archetype
                ],  # fmt: skip
                failed_case_ids=list(card.failed_case_ids),
                average_ms=round(sum(r.millis for r in done) / len(done), 1) if done else 0.0,
            )

    def report(self, case_id: str) -> LabReport:
        """Return the full report for one case (run it first to see its run and audit chain)."""
        with self._lock:
            if case_id not in self._specs:
                raise UnknownLabCaseError(case_id)
            spec, arch = self._specs[case_id]
            result = self._results.get(case_id)
            return LabReport(
                case=self._row(spec, arch),
                run=view_of(result.run) if result else None,
                audit=self._audit(result),
                account=self._profile(self._bank.get_account(spec.alert.account_id), spec),
            )

    def _audit(self, result: _Result | None) -> list[AuditEventView]:
        if result is None:
            return []
        return [
            AuditEventView(
                id=e.id,
                timestamp=e.timestamp,
                event_type=e.event_type.value,
                actor=f"{e.actor.kind.value}:{e.actor.id}",
                tool_name=e.tool_name,
                detail=e.detail,
                event_hash=e.event_hash,
            )
            for e in self._service.audit(result.run.case.id)
        ]

    # --- capability views ------------------------------------------------------------------
    def finished_runs(self) -> list[tuple[ScenarioSpec, str, CaseRun]]:
        """Finished runs of every lab case, running any that have not been run yet."""
        with self._lock:
            pending = [i for i in self._specs if i not in self._results]
        if pending:
            self.run(pending)
        with self._lock:
            return [(s, a, self._results[i].run) for i, (s, a) in self._specs.items()]

    @staticmethod
    def _card(c: Scorecard) -> CardView:
        return CardView(
            total=c.total, passed=c.passed, safe=c.safe, useful=c.useful, preferred=c.preferred,
            over_escalated=c.over_escalated, human_routed=c.human_routed, unjustified=c.unjustified,
        )  # fmt: skip

    def baselines(self) -> list[BaselineRow]:
        """Return the agents and each simple rule, scored on the same cases with the same checks."""
        runs = self.finished_runs()
        agents = scorecard([self._results[s.id].score for s, _, _ in runs])
        rows = [
            BaselineRow(
                key="agents",
                title="Nexa agents",
                description="Four agents, typed findings, hard gates, cited policy.",
                card=self._card(agents),
            )
        ]
        for result in run_baselines(self._bank, [(s, a) for s, a, _ in runs]):
            rows.append(
                BaselineRow(
                    key=result.key,
                    title=result.title,
                    description=result.description,
                    card=self._card(result.card),
                )  # fmt: skip
            )
        return rows

    def hostile(self) -> list[HostileRow]:
        """Misbehaving stand-in models behind the real gates, on every lab case."""
        return [
            HostileRow(
                key=r.key,
                title=r.title,
                description=r.description,
                total=r.total,
                raw_unsafe=r.raw_unsafe,
                safe=r.safe,
                useful=r.useful,
                gate_interventions=r.gate_interventions,
                fallbacks=r.fallbacks,
            )  # fmt: skip
            for r in run_hostile(self.finished_runs(), self._clock)
        ]

    def live(self) -> LiveView:
        """Return the latest saved live-model comparison, or ``available=False`` if none was run."""
        path = live_results_path()
        if not path.exists():
            return LiveView(available=False)
        data = json.loads(path.read_text(encoding="utf-8"))
        return LiveView(available=True, **data)

    # --- accounts --------------------------------------------------------------------------
    def accounts(self) -> list[AccountRow]:
        """Every account in the lab bank, with its case if one exists."""
        by_account = {s.alert.account_id: (s, a) for s, a in self._specs.values()}
        rows: list[AccountRow] = []
        for acc in self._bank.all_accounts():
            customer = self._bank.get_customer(acc.customer_id)
            spec, arch = by_account.get(acc.id, (None, None))
            rows.append(
                AccountRow(
                    account_id=acc.id,
                    customer_id=acc.customer_id,
                    name=customer.full_name,
                    city=customer.home_city,
                    risk_tier=customer.risk_tier.value,
                    balance=acc.balance,
                    status=acc.status.value,
                    archetype=arch,
                    case_id=spec.id if spec else None,
                )
            )
        return rows

    def account(self, account_id: str) -> AccountProfile:
        """Return the safe profile of one account."""
        try:
            acc = self._bank.get_account(account_id)
        except RecordNotFoundError:
            raise UnknownLabCaseError(account_id) from None
        spec = next((s for s, _ in self._specs.values() if s.alert.account_id == account_id), None)
        return self._profile(acc, spec)

    def _profile(self, acc: AccountRecord, spec: ScenarioSpec | None) -> AccountProfile:
        customer = self._bank.get_customer(acc.customer_id)
        kyc = self._bank.get_kyc(acc.customer_id)
        history = self._bank.list_transactions(acc.id)
        debits = [t.amount for t in history if t.direction.value == "debit"]
        alert_id = spec.alert.transaction_id if spec else None
        return AccountProfile(
            account_id=acc.id,
            customer_id=customer.id,
            name=customer.full_name,
            city=customer.home_city,
            home_country=customer.home_country,
            risk_tier=customer.risk_tier.value,
            product=acc.product,
            status=acc.status.value,
            card_status=acc.card_status.value,
            balance=acc.balance,
            travel_notices=[
                f"{n.country} {n.from_date} to {n.to_date}" for n in customer.travel_notices
            ],
            kyc_status=kyc.status.value,
            kyc_missing=list(kyc.missing_items),
            address_on_file=customer.address,
            address_on_document=kyc.address_on_document,
            payments=len(history),
            average_debit=round(sum(debits) / len(debits)) if debits else 0,
            countries=sorted({t.country for t in history}),
            recent=[
                TransactionView(
                    id=t.id,
                    occurred_at=t.occurred_at.isoformat(),
                    direction=t.direction.value,
                    amount=t.amount,
                    country=t.country,
                    channel=t.channel.value,
                    device_trusted=t.device_trusted,
                    is_new_beneficiary=t.is_new_beneficiary,
                    failed_auth_attempts=t.failed_auth_attempts_prior_hour,
                    is_alert=t.id == alert_id,
                )
                for t in history[-40:]
            ],
        )
