import json
from datetime import datetime, timezone
from engine.resolvers.shadow_runner import DriftLog, DriftRecord, ShadowResult


def _make_record(key: str = "k") -> DriftRecord:
    return DriftRecord(
        step_key=key,
        timestamp=datetime.now(timezone.utc).isoformat(),
        description="test step",
        winner_method="role",
        winner_confidence=0.95,
        shadow_results=[ShadowResult(strategy="css", found=True, agrees=True, confidence=0.75)],
        drift_score=0.0,
    )


def test_empty_log_no_file(tmp_path):
    log_path = tmp_path / "drift.json"
    log = DriftLog(log_path)
    assert log.latest(5) == []
    assert not log_path.exists()


def test_append_stores_record(tmp_path):
    log = DriftLog(tmp_path / "drift.json")
    log.append(_make_record("step1"))
    result = log.latest(1)
    assert len(result) == 1
    assert result[0]["step_key"] == "step1"


def test_flush_every_10(tmp_path):
    log_path = tmp_path / "drift.json"
    log = DriftLog(log_path)
    for i in range(10):
        log.append(_make_record(str(i)))
    assert log_path.exists()
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(data) == 10


def test_no_flush_before_10(tmp_path):
    log_path = tmp_path / "drift.json"
    log = DriftLog(log_path)
    for i in range(9):
        log.append(_make_record(str(i)))
    assert not log_path.exists()


def test_cap_at_500(tmp_path):
    log = DriftLog(tmp_path / "drift.json")
    for i in range(510):
        log.append(_make_record(str(i)))
    assert len(log._records) == 500
    # First 10 records should have been evicted
    assert log._records[0]["step_key"] == "10"


def test_flush_force(tmp_path):
    log_path = tmp_path / "drift.json"
    log = DriftLog(log_path)
    log.append(_make_record())
    assert not log_path.exists()  # 1 < 10, no auto-flush yet
    log.flush()
    assert log_path.exists()


def test_flush_noop_when_nothing_unflushed(tmp_path):
    log_path = tmp_path / "drift.json"
    log = DriftLog(log_path)
    for i in range(10):
        log.append(_make_record(str(i)))
    assert log._unflushed == 0
    log.flush()  # should not raise


def test_load_existing_file(tmp_path):
    log_path = tmp_path / "drift.json"
    existing = [
        {"step_key": f"k{i}", "drift_score": 0.0, "shadow_results": []}
        for i in range(3)
    ]
    log_path.write_text(json.dumps(existing), encoding="utf-8")
    log = DriftLog(log_path)
    assert len(log.latest(10)) == 3
