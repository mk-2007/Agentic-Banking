import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nexa.audit import AuditRecorder, AuditTamperedError, InMemoryAuditLog, JsonlAuditLog
from nexa.domain.actors import Actor, ActorKind, Role
from nexa.domain.audit import GENESIS_HASH, AuditEventType

ACTOR = Actor(kind=ActorKind.AGENT, id="a1", role=Role.DATA_AGENT)
FIXED = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def recorder(log: InMemoryAuditLog) -> AuditRecorder:
    return AuditRecorder(log, clock=lambda: FIXED)


def test_events_are_chained_from_genesis() -> None:
    log = InMemoryAuditLog()
    rec = recorder(log)
    first = rec.record(AuditEventType.CASE_CREATED, ACTOR, case_id="case_1")
    second = rec.record(AuditEventType.STATE_CHANGED, ACTOR, case_id="case_1", detail="x")
    assert first.prev_hash == GENESIS_HASH
    assert second.prev_hash == first.event_hash
    assert log.verify() is None
    assert [e.id for e in log.events()] == [first.id, second.id]


def test_recorder_uses_the_injected_clock() -> None:
    log = InMemoryAuditLog()
    event = recorder(log).record(AuditEventType.ERROR, ACTOR)
    assert event.timestamp == FIXED


def test_for_case_filters_events() -> None:
    log = InMemoryAuditLog()
    rec = recorder(log)
    rec.record(AuditEventType.CASE_CREATED, ACTOR, case_id="case_1")
    rec.record(AuditEventType.CASE_CREATED, ACTOR, case_id="case_2")
    assert len(log.for_case("case_1")) == 1


def test_the_log_has_no_way_to_change_history() -> None:
    log = InMemoryAuditLog()
    assert not any(hasattr(log, name) for name in ("update", "delete", "remove", "clear", "pop"))
    snapshot = log.events()
    recorder(log).record(AuditEventType.ERROR, ACTOR)
    assert snapshot == ()  # earlier snapshots are unaffected by later appends


def test_concurrent_appends_keep_the_chain_intact() -> None:
    log = InMemoryAuditLog()
    rec = recorder(log)

    def work() -> None:
        for _ in range(25):
            rec.record(AuditEventType.TOOL_CALLED, ACTOR)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(log.events()) == 200
    assert log.verify() is None


def test_jsonl_log_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "log.jsonl"
    log = JsonlAuditLog(path)
    rec = recorder(log)
    rec.record(AuditEventType.CASE_CREATED, ACTOR, case_id="case_1")
    rec.record(AuditEventType.STATE_CHANGED, ACTOR, case_id="case_1")

    reopened = JsonlAuditLog(path)
    assert reopened.events() == log.events()
    recorder(reopened).record(AuditEventType.ERROR, ACTOR)  # keeps chaining after reload
    assert JsonlAuditLog(path).verify() is None
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_editing_the_file_is_detected_on_open(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    rec = recorder(JsonlAuditLog(path))
    rec.record(AuditEventType.CASE_CREATED, ACTOR, case_id="case_1", detail="original")
    rec.record(AuditEventType.STATE_CHANGED, ACTOR, case_id="case_1")
    path.write_text(
        path.read_text(encoding="utf-8").replace("original", "doctored"), encoding="utf-8"
    )
    with pytest.raises(AuditTamperedError):
        JsonlAuditLog(path)


def test_deleting_a_line_is_detected_on_open(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    rec = recorder(JsonlAuditLog(path))
    for _ in range(3):
        rec.record(AuditEventType.TOOL_CALLED, ACTOR)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(AuditTamperedError, match="broken"):
        JsonlAuditLog(path)


def test_garbage_in_the_file_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(AuditTamperedError):
        JsonlAuditLog(path)
