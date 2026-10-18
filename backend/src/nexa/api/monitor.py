"""The watch on the customer app: every posted payment is reviewed, and some open a case.

The customer's payment is posted first and answered at once; the review runs in the background so a
slow investigation never holds up a payment. For each payment the monitor builds a typed digest from
the bank's records (the monitor agent never touches the bank), then:

1. a payment that crosses a policy threshold opens a case (the floor, plain code);
2. one that is ordinary in every respect is cleared (plain code);
3. anything else is put to a model, which opens or clears it with a reason from a closed list, and
   a missing or failing model opens it.

A burst on one account does not open a case per payment: while a case opened by the monitor is
recent, further payments with the same reasons are linked to it, and a reason that is new (the fifth
payment in an hour, say) opens a new one. Everything is logged for the employee's live feed, as
codes and ids only.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from nexa.agents.monitor_agent import (
    DIGITAL,
    MonitorAgent,
    TransactionDigest,
    floor_reasons,
    is_routine,
)
from nexa.bank_sim.gateway import BankGateway
from nexa.bank_sim.models import TransactionRecord
from nexa.config import DEFAULT_THRESHOLDS, FraudThresholds

from .service import CaseService

LINK_WINDOW = timedelta(minutes=30)  # a recent monitor case on the same account absorbs a burst
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)


class Path(StrEnum):
    """Which way a payment was decided."""

    FLOOR = "floor"
    ROUTINE = "routine"
    MODEL = "model"
    MODEL_UNAVAILABLE = "model_unavailable"


class Decision(StrEnum):
    """What the monitor did with a payment."""

    OPENED = "opened"
    LINKED = "linked"
    CLEARED = "cleared"
    ERROR = "error"


class Phase(StrEnum):
    """Where the review is."""

    REVIEWING = "reviewing"
    INVESTIGATING = "investigating"
    DONE = "done"


@dataclass
class MonitorEntry:
    """One reviewed payment. Codes and ids only: no merchant text."""

    transaction_id: str
    account_id: str
    amount: int
    observed_at: datetime
    phase: Phase = Phase.REVIEWING
    decision: Decision | None = None
    path: Path | None = None
    reasons: tuple[str, ...] = ()
    case_id: str | None = None
    case_status: str | None = None
    opened_reasons: frozenset[str] = field(default_factory=frozenset, repr=False)


def build_digest(
    bank: BankGateway, txn: TransactionRecord, t: FraudThresholds = DEFAULT_THRESHOLDS
) -> TransactionDigest:
    """Summarise ``txn`` against the account's own earlier activity, as numbers and flags."""
    account = bank.get_account(txn.account_id)
    customer = bank.get_customer(account.customer_id)
    since = txn.occurred_at - timedelta(days=t.history_lookback_days)
    prior = [
        h
        for h in bank.list_transactions(txn.account_id, since=since, until=txn.occurred_at)
        if h.id != txn.id
    ]
    window_start = txn.occurred_at - timedelta(minutes=t.velocity_window_minutes)
    baseline = [h for h in prior if h.occurred_at < window_start and h.direction.value == "debit"]
    average = sum(h.amount for h in baseline) / len(baseline) if baseline else None
    enough = len(prior) >= t.min_history_transactions
    line = t.high_value_amount_pkr
    day = [h for h in prior if h.occurred_at >= txn.occurred_at - DAY]
    same_way = [h for h in day if h.direction == txn.direction]
    near = [h for h in same_way if t.structuring_band_floor * line <= h.amount < line]
    near_now = int(t.structuring_band_floor * line <= txn.amount < line)
    today = txn.occurred_at.date()
    covered = any(
        n.country == txn.country and n.from_date <= today <= n.to_date
        for n in customer.travel_notices
    )
    spent = sum(h.amount for h in same_way) + txn.amount
    return TransactionDigest(
        transaction_id=txn.id,
        direction=txn.direction.value,
        channel=txn.channel.value,
        amount=txn.amount,
        prior_transactions=len(prior),
        ratio_to_average=round(txn.amount / average, 1) if average and enough else None,
        payments_last_hour=1 + sum(h.occurred_at >= txn.occurred_at - HOUR for h in same_way),
        payments_last_day=1 + len(same_way),
        total_last_day=spent,
        near_line_last_day=len(near) + near_now,
        new_payee=txn.is_new_beneficiary,
        device_trusted=txn.device_trusted or txn.channel.value not in DIGITAL,
        failed_logins=txn.failed_auth_attempts_prior_hour,
        abroad=txn.country != customer.home_country,
        travel_notice_covers=covered,
        country_seen_before=any(h.country == txn.country for h in prior),
        merchant_seen_before=any(
            h.merchant_name.casefold() == txn.merchant_name.casefold() for h in prior
        ),
        share_of_balance=round(txn.amount / max(1, account.balance + txn.amount), 2),
    )


class Monitor:
    """Reviews each posted payment in the background and opens cases as needed."""

    def __init__(
        self,
        bank: BankGateway,
        service: CaseService,
        agent: MonitorAgent,
        *,
        thresholds: FraudThresholds = DEFAULT_THRESHOLDS,
        executor: Executor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._bank = bank
        self._service = service
        self._agent = agent
        self._t = thresholds
        # One worker: investigations go through a free-tier model, so they are taken in turn.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="monitor")
        self._clock = clock or service.now
        self._lock = threading.Lock()
        self._entries: list[MonitorEntry] = []
        self._recent: dict[str, MonitorEntry] = {}  # account id -> its latest monitor-opened case

    def watch(self, txn: TransactionRecord) -> MonitorEntry:
        """Queue ``txn`` for review and return its log entry (updated as the review proceeds)."""
        entry = MonitorEntry(txn.id, txn.account_id, txn.amount, txn.occurred_at)
        with self._lock:
            self._entries.append(entry)
        self._executor.submit(self._run, entry, txn)
        return entry

    def entries(self) -> list[MonitorEntry]:
        """Return the log, newest first."""
        with self._lock:
            return list(reversed(self._entries))

    # --- the review ------------------------------------------------------------------------
    def _run(self, entry: MonitorEntry, txn: TransactionRecord) -> None:
        try:
            self._review(entry, txn)
        except Exception:  # noqa: BLE001 - a review must never take the worker down
            entry.decision, entry.phase = Decision.ERROR, Phase.DONE

    def _review(self, entry: MonitorEntry, txn: TransactionRecord) -> None:
        digest = build_digest(self._bank, txn, self._t)
        floor = floor_reasons(digest, self._t)
        if floor:
            entry.path, reasons = Path.FLOOR, tuple(r.value for r in floor)
        elif is_routine(digest, self._t):
            entry.path, entry.reasons = Path.ROUTINE, ("routine",)
            entry.decision, entry.phase = Decision.CLEARED, Phase.DONE
            return
        else:
            triage = self._agent.triage(digest)
            if triage is None:  # no model, or it failed: open the case rather than guess
                entry.path, reasons = Path.MODEL_UNAVAILABLE, ("model_unavailable",)
            elif triage.open_case:
                entry.path, reasons = Path.MODEL, (triage.reason.value,)
            else:
                entry.path, entry.reasons = Path.MODEL, (triage.reason.value,)
                entry.decision, entry.phase = Decision.CLEARED, Phase.DONE
                return
        entry.reasons = reasons

        earlier = self._linked(txn, reasons)
        if earlier is not None:
            entry.decision, entry.phase = Decision.LINKED, Phase.DONE
            entry.case_id, entry.case_status = earlier.case_id, earlier.case_status
            return
        entry.phase = Phase.INVESTIGATING
        entry.opened_reasons = frozenset(reasons)
        with self._lock:
            self._recent[txn.account_id] = entry
        run = self._service.open_case(
            account_id=txn.account_id,
            customer_id=self._bank.get_account(txn.account_id).customer_id,
            transaction_id=txn.id,
            trigger=f"monitor:{entry.path.value}:{reasons[0]}",
        )
        entry.case_id, entry.case_status = run.case.id, run.case.status.value
        entry.decision, entry.phase = Decision.OPENED, Phase.DONE

    def _linked(self, txn: TransactionRecord, reasons: tuple[str, ...]) -> MonitorEntry | None:
        """Return the recent case that already covers ``reasons`` on this account, if any."""
        with self._lock:
            recent = self._recent.get(txn.account_id)
        if recent is None or recent.case_id is None:
            return None
        if txn.occurred_at - recent.observed_at > LINK_WINDOW:
            return None
        return recent if set(reasons) <= recent.opened_reasons else None
