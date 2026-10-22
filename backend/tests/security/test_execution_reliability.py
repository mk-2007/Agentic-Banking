"""Retries on a flaky bank, the failure record, and reconciliation against the audit log."""

from conftest import EXECUTOR, Env
from test_execution_gate import execute

from nexa.bank_sim.models import AccountStatus
from nexa.domain.audit import AuditEventType
from nexa.tools import Mismatch, TransientBankError, reconcile
from nexa.tools.execution import MAX_ATTEMPTS


class FlakyBank:
    """Wraps the real bank; the first ``failures`` freeze calls time out."""

    def __init__(self, real: object, failures: int) -> None:
        self._real, self.failures, self.calls = real, failures, 0

    def freeze_account(self, account_id: str) -> object:
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientBankError("timeout")
        return self._real.freeze_account(account_id)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def flaky(env: Env, failures: int) -> FlakyBank:
    bank = FlakyBank(env.bank, failures)
    object.__setattr__(env.ctx, "bank", bank)  # the context is frozen; tests may swap the bank
    return bank


def test_a_timeout_is_retried_and_the_action_applies_once(env: Env) -> None:
    bank = flaky(env, failures=MAX_ATTEMPTS - 1)
    result = execute(env, approval_id=env.freeze_approval())
    assert result.ok and bank.calls == MAX_ATTEMPTS
    assert env.bank.get_account("acc_106").status is AccountStatus.FROZEN
    kinds = [e.event_type for e in env.log.events()]
    assert kinds.count(AuditEventType.ACTION_EXECUTED) == 1
    assert reconcile(env.log.events(), env.bank) == []


def test_a_bank_that_stays_down_is_reported_for_follow_up(env: Env) -> None:
    flaky(env, failures=99)
    result = execute(env, approval_id=env.freeze_approval())
    assert not result.ok
    assert env.bank.get_account("acc_106").status is AccountStatus.ACTIVE
    assert reconcile(env.log.events(), env.bank) == [
        Mismatch("execution_failed", "case_f", "acc_106", "freeze_account")
    ]
    assert not execute(env, approval_id="apr_1").ok  # the spent approval cannot be replayed


def test_reconciliation_catches_a_logged_action_the_bank_does_not_show(env: Env) -> None:
    env.ctx.audit.record(  # the log claims a freeze the bank never applied
        AuditEventType.ACTION_EXECUTED,
        EXECUTOR,
        case_id="case_f",
        output_ref="freeze_account:acc_106",
    )
    assert reconcile(env.log.events(), env.bank) == [
        Mismatch("not_applied", "case_f", "acc_106", "freeze_account")
    ]
    ok = execute(env, approval_id=env.freeze_approval())
    assert ok.ok and reconcile(env.log.events(), env.bank) == []
