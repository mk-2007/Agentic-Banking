"""Runs labelled, randomised traffic through the real path and scores what the platform did.

Each episode gets a fresh simulated bank, case service and monitor, so episodes cannot
contaminate one another. A persona's events are posted as a customer would (through
`LiveService.pay`) or, for cash
deposits, straight to the bank; every posted transaction is handed to the monitor, which opens cases
exactly as it does for the customer app. The platform's recommendations are then judged against the
persona's label (see `nexa.evaluation.simulator`).

Used by `scripts/run_sim_eval.py`. The server never runs it: like the live-model lab it only
reads the file the script saves, so no request ever waits on a model.
"""

import time
from concurrent.futures import Executor, Future
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from nexa.agents import code_of
from nexa.agents.monitor_agent import MonitorAgent
from nexa.bank_sim import load_bank
from nexa.bank_sim.models import Channel, Direction, TransactionRecord
from nexa.config import DEFAULT_THRESHOLDS
from nexa.decision import LlmDecisionProvider, RuleBasedDecisionProvider
from nexa.domain.ids import new_id
from nexa.evaluation.simulator import (
    LABELS,
    PERSONAS,
    EpisodeScore,
    Profile,
    SimEvent,
    generate,
    judge_episode,
    summarise,
)
from nexa.llm import LlmGateway
from nexa.rag import KnowledgeSearch, load_knowledge_base

from .live import LiveService
from .monitor import Monitor
from .schemas import PaymentRequest
from .service import CaseService

BACKGROUND_PREFIX = "cust_0"  # the ordinary customers, not the scenario ones
MIN_HISTORY = 25


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now


class _Inline(Executor):
    """Runs each review at once, so an episode is finished when its last payment is posted."""

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        future: Future[None] = Future()
        fn(*args, **kwargs)
        future.set_result(None)
        return future


@dataclass
class EpisodeResult:
    """Everything about one episode, ready to save as JSON."""

    persona: str
    seed: int
    account_id: str
    events: int
    refused: int
    score: EpisodeScore
    monitor: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    tokens: int = 0


class SimulationRunner:
    """Builds a fresh platform per episode and runs a persona through it."""

    def __init__(
        self,
        gateway: LlmGateway | None = None,
        *,
        llm_decisions: bool = False,
        knowledge: KnowledgeSearch | None = None,
    ) -> None:
        self._gateway = gateway
        self._llm_decisions = llm_decisions and gateway is not None
        self._knowledge = knowledge or load_knowledge_base()

    @staticmethod
    def accounts() -> list[str]:
        """Return the ordinary accounts episodes may run on (enough history, PK, funded)."""
        bank = load_bank()
        found = []
        for account in bank.all_accounts():
            customer = bank.get_customer(account.customer_id)
            enough = len(bank.list_transactions(account.id)) >= MIN_HISTORY
            if (
                account.customer_id.startswith(BACKGROUND_PREFIX)
                and enough
                and account.balance >= 100_000
                and customer.home_country == "PK"
            ):
                found.append(account.id)
        return sorted(found)

    def run_episode(self, persona: str, seed: int, account_id: str) -> EpisodeResult:
        """Post ``persona``'s payments for ``seed`` on ``account_id`` and judge the outcome."""
        started = time.time()
        bank = load_bank()
        clock = _Clock()
        provider = (
            LlmDecisionProvider(self._gateway, clock, RuleBasedDecisionProvider(clock))
            if self._llm_decisions and self._gateway is not None
            else None
        )
        service = CaseService(
            bank=bank,
            knowledge=self._knowledge,
            gateway=self._gateway,
            provider=provider,
            clock=clock,
        )
        monitor = Monitor(
            bank,
            service,
            MonitorAgent(self._gateway, DEFAULT_THRESHOLDS),
            executor=_Inline(),
            clock=clock,
        )
        live = LiveService(bank, clock)
        account = bank.get_account(account_id)
        customer = bank.get_customer(account.customer_id)
        debits = [
            t.amount for t in bank.list_transactions(account_id) if t.direction is Direction.DEBIT
        ]
        profile = Profile(
            avg_debit=sum(debits) // max(1, len(debits)),
            home_country=customer.home_country,
            home_city=customer.home_city,
            balance=account.balance,
        )
        events = generate(persona, seed, profile)
        refused = 0
        for event in events:
            clock.now += timedelta(minutes=event.minutes_after_previous or 1)
            record = self._post(live, bank, account.customer_id, account_id, event, clock.now)
            if record is None:
                refused += 1
                continue
            monitor.watch(record)

        entries = list(reversed(monitor.entries()))  # oldest first
        cases: list[dict[str, Any]] = []
        actions = []
        codes: set[str] = set()
        tokens = 0
        for case_id in dict.fromkeys(e.case_id for e in entries if e.case_id):
            run = service.get(case_id)
            if run.decision is not None:
                actions.append(run.decision.recommended_action)
            tokens += run.inquiry.tokens if run.inquiry else 0
            found = [
                c.value
                for e in (run.investigation.findings if run.investigation else ())
                if (c := code_of(e))
            ]
            codes.update(found)
            cases.append(
                {
                    "case_id": case_id,
                    "status": run.case.status.value,
                    "action": run.decision.recommended_action.value if run.decision else None,
                    "overridden_by": run.decision.overridden_by if run.decision else None,
                    "findings": found,
                    "inquiry": run.inquiry.model_dump(mode="json") if run.inquiry else None,
                }
            )
        return EpisodeResult(
            persona=persona,
            seed=seed,
            account_id=account_id,
            events=len(events),
            refused=refused,
            score=judge_episode(persona, seed, actions, frozenset(codes)),
            monitor=[
                {
                    "amount": e.amount,
                    "path": e.path.value if e.path else None,
                    "decision": e.decision.value if e.decision else None,
                    "reasons": list(e.reasons),
                    "case_id": e.case_id,
                }
                for e in entries
            ],
            cases=cases,
            seconds=round(time.time() - started, 1),
            tokens=tokens,
        )

    @staticmethod
    def _post(
        live: LiveService,
        bank: Any,
        customer_id: str,
        account_id: str,
        event: SimEvent,
        now: datetime,
    ) -> TransactionRecord | None:
        try:
            if event.kind == "deposit":
                record = TransactionRecord(
                    id=new_id("txn"),
                    account_id=account_id,
                    occurred_at=now,
                    direction=Direction.CREDIT,
                    amount=event.amount,
                    merchant_name=event.merchant,
                    merchant_category=event.category,
                    country=event.country,
                    city=event.city,
                    channel=Channel(event.channel),
                    device_trusted=False,
                )
                return bank.add_transaction(record)  # type: ignore[no-any-return]
            record, _ = live.pay(
                customer_id,
                PaymentRequest(
                    account_id=account_id,
                    amount=event.amount,
                    merchant_name=event.merchant,
                    merchant_category=event.category,  # type: ignore[arg-type]
                    country=event.country,
                    city=event.city,
                    channel=event.channel,  # type: ignore[arg-type]
                    payee_account=event.payee,
                    device=event.device,
                    failed_logins=event.failed_logins,
                ),
            )
            return record
        except Exception:  # noqa: BLE001 - a refused payment (funds, a frozen account) is an outcome
            return None


def run_simulation(
    runner: SimulationRunner,
    seeds: list[int],
    personas: tuple[str, ...] = PERSONAS,
    on_episode: Any = None,
) -> dict[str, Any]:
    """Run every persona for every seed and return the episodes and their summary as JSON data."""
    accounts = runner.accounts()
    results: list[EpisodeResult] = []
    for n, (seed, persona) in enumerate((s, p) for s in seeds for p in personas):
        result = runner.run_episode(persona, seed, accounts[n % len(accounts)])
        results.append(result)
        if on_episode is not None:
            on_episode(result)
    summary = summarise([r.score for r in results])
    return {
        "episodes": [asdict(r) for r in results],
        "summary": asdict(summary),
        "labels": {p: {"kind": LABELS[p].kind.value, "story": LABELS[p].story} for p in PERSONAS},
    }
