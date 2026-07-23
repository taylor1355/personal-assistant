"""Unit tests for the Hermes gateway supervisor's pure logic (PA-104).

The module lives under tools/ (stdlib-only, no package install), so we add it
to sys.path rather than importing it as part of personal_assistant_agent. Every
test drives the PURE functions directly or injects fake Boundaries — no real
subprocess, filesystem, or clock. `now` is always an explicit datetime.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

import hermes_gateway_supervisor as s  # noqa: E402

T0 = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)

_PID_RECORD = {
    "pid": 22148,
    "kind": "hermes-gateway",
    "argv": ["C:\\Users\\taylor\\Dev\\hermes-agent\\hermes_cli\\main.py", "gateway", "run"],
    "start_time": None,
}


def _proc(pid: int = 22148, name: str = "python.exe", cmdline: str = "") -> s.ProcessInfo:
    return s.ProcessInfo(pid=pid, name=name, cmdline=cmdline)


_GATEWAY_CMDLINE = (
    '"C:\\...\\python.exe" -m hermes_cli.main gateway run'
)


# --------------------------------------------------------------------------
# is_gateway_process
# --------------------------------------------------------------------------


def test_is_gateway_process_matches_python_with_hermes_cmdline():
    assert s.is_gateway_process(_proc(cmdline=_GATEWAY_CMDLINE), _PID_RECORD) is True


def test_is_gateway_process_accepts_pythonw_image():
    proc = _proc(name="pythonw.exe", cmdline=_GATEWAY_CMDLINE)
    assert s.is_gateway_process(proc, _PID_RECORD) is True


def test_is_gateway_process_rejects_unrelated_image():
    proc = _proc(name="notepad.exe", cmdline=_GATEWAY_CMDLINE)
    assert s.is_gateway_process(proc, _PID_RECORD) is False


def test_is_gateway_process_matches_recorded_argv_path():
    # cmdline names the recorded main.py path but not the "hermes_cli"+"gateway
    # run" combo directly — the argv-path fallback must still match it.
    cmd_argv_only = '"python.exe" C:\\Users\\taylor\\Dev\\hermes-agent\\hermes_cli\\main.py serve'
    assert s.is_gateway_process(_proc(cmdline=cmd_argv_only), _PID_RECORD) is True


def test_is_gateway_process_rejects_python_without_hermes():
    assert s.is_gateway_process(_proc(cmdline='"python.exe" -m http.server'), _PID_RECORD) is False


def test_is_gateway_process_no_record_still_matches_direct_cmdline():
    assert s.is_gateway_process(_proc(cmdline=_GATEWAY_CMDLINE), None) is True


def test_is_gateway_process_empty_argv_falls_through_to_false():
    # Record present but argv empty: the fallback loop is skipped, returns False.
    record = {"pid": 22148, "argv": []}
    assert s.is_gateway_process(_proc(cmdline='"python.exe" -m other'), record) is False


def test_is_gateway_process_non_string_argv_token_ignored():
    # A non-string argv token must not crash the endswith() check.
    record = {"pid": 22148, "argv": [123, None]}
    assert s.is_gateway_process(_proc(cmdline='"python.exe" -m other'), record) is False


def test_is_gateway_process_python_no_record_non_matching_cmdline_is_false():
    # python image, no record, cmdline lacks the direct match -> falls to False.
    assert s.is_gateway_process(_proc(cmdline='"python.exe" -m other'), None) is False


def test_is_gateway_process_record_without_argv_is_false():
    # Record present but no argv key -> .get returns None, not a list -> False.
    record = {"pid": 22148, "kind": "hermes-gateway"}
    assert s.is_gateway_process(_proc(cmdline='"python.exe" -m other'), record) is False


# --------------------------------------------------------------------------
# classify_liveness
# --------------------------------------------------------------------------


def test_classify_liveness_missing_pidfile_is_dead():
    assert s.classify_liveness(None, None) is s.Liveness.DEAD


def test_classify_liveness_unparseable_pid_is_dead():
    assert s.classify_liveness({"kind": "x"}, _proc()) is s.Liveness.DEAD


def test_classify_liveness_no_process_is_dead():
    assert s.classify_liveness(_PID_RECORD, None) is s.Liveness.DEAD


def test_classify_liveness_matching_process_is_alive():
    proc = _proc(cmdline=_GATEWAY_CMDLINE)
    assert s.classify_liveness(_PID_RECORD, proc) is s.Liveness.ALIVE


def test_classify_liveness_pythonw_is_alive():
    proc = _proc(name="pythonw.exe", cmdline=_GATEWAY_CMDLINE)
    assert s.classify_liveness(_PID_RECORD, proc) is s.Liveness.ALIVE


def test_classify_liveness_pid_reused_by_notepad_is_dead():
    # Critical regression: recorded PID reused by an unrelated process.
    reused = _proc(name="notepad.exe", cmdline='"C:\\notepad.exe" note.txt')
    assert s.classify_liveness(_PID_RECORD, reused) is s.Liveness.DEAD


def test_classify_liveness_python_without_hermes_is_dead():
    other = _proc(name="python.exe", cmdline='"python.exe" -m http.server 8000')
    assert s.classify_liveness(_PID_RECORD, other) is s.Liveness.DEAD


def test_classify_liveness_empty_cmdline_is_ambiguous():
    # Right image, unreadable cmdline -> do not restart.
    blank = _proc(name="python.exe", cmdline="")
    assert s.classify_liveness(_PID_RECORD, blank) is s.Liveness.AMBIGUOUS


def test_classify_liveness_recorded_argv_path_is_alive():
    cmd = '"python.exe" C:\\Users\\taylor\\Dev\\hermes-agent\\hermes_cli\\main.py serve'
    assert s.classify_liveness(_PID_RECORD, _proc(cmdline=cmd)) is s.Liveness.ALIVE


# --------------------------------------------------------------------------
# decide_next_action — healthy paths
# --------------------------------------------------------------------------


def test_decide_alive_sleeps_poll_interval():
    action, state = s.decide_next_action(s.SupervisorState(), s.Liveness.ALIVE, T0)
    assert action.kind is s.ActionKind.SLEEP
    assert action.seconds == float(s.POLL_SECONDS)


def test_decide_ambiguous_sleeps_and_does_not_restart():
    action, _ = s.decide_next_action(s.SupervisorState(), s.Liveness.AMBIGUOUS, T0)
    assert action.kind is s.ActionKind.SLEEP


def test_decide_alive_resets_failures_after_stabilize():
    prior = s.SupervisorState(
        consecutive_failures=3,
        last_restart_at=T0,
    )
    later = T0 + timedelta(seconds=s.STABILIZE_SECONDS + 1)
    _, state = s.decide_next_action(prior, s.Liveness.ALIVE, later)
    assert state.consecutive_failures == 0
    assert state.last_restart_at is None


def test_decide_alive_keeps_failures_before_stabilize():
    prior = s.SupervisorState(consecutive_failures=2, last_restart_at=T0)
    soon = T0 + timedelta(seconds=s.STABILIZE_SECONDS - 5)
    _, state = s.decide_next_action(prior, s.Liveness.ALIVE, soon)
    assert state.consecutive_failures == 2


# --------------------------------------------------------------------------
# decide_next_action — restart / backoff
# --------------------------------------------------------------------------


def test_decide_first_death_restarts_with_first_backoff():
    action, state = s.decide_next_action(s.SupervisorState(), s.Liveness.DEAD, T0)
    assert action.kind is s.ActionKind.RESTART
    assert action.seconds == float(s.BACKOFF_SECONDS[0])  # 5
    assert state.consecutive_failures == 1
    assert state.last_restart_at == T0


def test_decide_backoff_increases_exponentially():
    state = s.SupervisorState()
    seen: list[float] = []
    moment = T0
    for _ in range(3):
        action, state = s.decide_next_action(state, s.Liveness.DEAD, moment)
        seen.append(action.seconds)
        moment += timedelta(seconds=1)
    assert seen == [5.0, 15.0, 60.0]


def test_decide_backoff_caps_at_max():
    state = s.SupervisorState()
    moment = T0
    last = 0.0
    for _ in range(5):
        action, state = s.decide_next_action(state, s.Liveness.DEAD, moment)
        last = action.seconds
        moment += timedelta(seconds=1)
    # 5th death (still under CB_MAX) uses the capped backoff.
    assert last == float(s.BACKOFF_SECONDS[-1])  # 300


# --------------------------------------------------------------------------
# decide_next_action — circuit breaker
# --------------------------------------------------------------------------


def test_decide_sixth_death_in_window_trips_breaker():
    state = s.SupervisorState()
    moment = T0
    for _ in range(s.CB_MAX):  # 5 restarts recorded
        action, state = s.decide_next_action(state, s.Liveness.DEAD, moment)
        assert action.kind is s.ActionKind.RESTART
        moment += timedelta(seconds=1)
    # 6th within the window -> trip.
    action, state = s.decide_next_action(state, s.Liveness.DEAD, moment)
    assert action.kind is s.ActionKind.TRIPPED_WAIT
    assert action.seconds == float(s.CB_COOLDOWN_SECONDS)
    assert state.tripped_until == datetime.fromtimestamp(
        moment.timestamp() + s.CB_COOLDOWN_SECONDS, tz=UTC
    )


def test_decide_stays_tripped_during_cooldown():
    tripped_until = T0 + timedelta(seconds=s.CB_COOLDOWN_SECONDS)
    state = s.SupervisorState(tripped_until=tripped_until)
    mid = T0 + timedelta(seconds=60)
    action, new_state = s.decide_next_action(state, s.Liveness.DEAD, mid)
    assert action.kind is s.ActionKind.TRIPPED_WAIT
    assert action.seconds == pytest.approx(s.CB_COOLDOWN_SECONDS - 60)
    assert new_state.tripped_until == tripped_until  # unchanged, no new restart


def test_decide_restarts_after_cooldown_expires():
    tripped_until = T0 + timedelta(seconds=s.CB_COOLDOWN_SECONDS)
    # After the window fully elapses, old restart_times fall out of CB_WINDOW too.
    after = tripped_until + timedelta(seconds=1)
    old_restarts = tuple(T0 - timedelta(seconds=i) for i in range(s.CB_MAX))
    state = s.SupervisorState(
        consecutive_failures=s.CB_MAX,
        restart_times=old_restarts,
        tripped_until=tripped_until,
    )
    action, new_state = s.decide_next_action(state, s.Liveness.DEAD, after)
    assert action.kind is s.ActionKind.RESTART
    assert new_state.tripped_until is None


def test_decide_window_slides_old_restarts_out():
    # Restarts older than CB_WINDOW don't count toward the breaker.
    old = tuple(T0 - timedelta(seconds=s.CB_WINDOW_SECONDS + 100 + i) for i in range(s.CB_MAX))
    state = s.SupervisorState(consecutive_failures=s.CB_MAX, restart_times=old)
    action, _ = s.decide_next_action(state, s.Liveness.DEAD, T0)
    assert action.kind is s.ActionKind.RESTART


# --------------------------------------------------------------------------
# SupervisorState helpers
# --------------------------------------------------------------------------


def test_state_record_restart_appends_and_increments():
    state = s.SupervisorState().record_restart(T0)
    assert state.consecutive_failures == 1
    assert state.restart_times == (T0,)
    assert state.last_restart_at == T0


def test_state_reset_failures_clears_counters():
    state = s.SupervisorState(consecutive_failures=4, last_restart_at=T0).reset_failures()
    assert state.consecutive_failures == 0
    assert state.last_restart_at is None


def test_state_restarts_within_counts_only_in_window():
    times = (T0 - timedelta(seconds=10), T0 - timedelta(seconds=1000))
    state = s.SupervisorState(restart_times=times)
    assert state.restarts_within(T0, 60) == 1


# --------------------------------------------------------------------------
# should_yield_to_existing
# --------------------------------------------------------------------------


_LOCK = {"pid": 999, "kind": "hermes-gateway-supervisor"}


def test_should_yield_when_live_supervisor_holds_lock():
    proc = _proc(pid=999, name="pythonw.exe", cmdline="pythonw tools\\hermes_gateway_supervisor.py")
    assert s.should_yield_to_existing(_LOCK, proc) is True


def test_should_claim_when_lock_pid_dead():
    assert s.should_yield_to_existing(_LOCK, None) is False


def test_should_claim_when_pid_reused_by_unrelated():
    proc = _proc(pid=999, name="notepad.exe", cmdline="notepad note.txt")
    assert s.should_yield_to_existing(_LOCK, proc) is False


def test_should_claim_when_no_lock_file():
    assert s.should_yield_to_existing(None, None) is False


def test_should_claim_when_lock_pid_unparseable():
    assert s.should_yield_to_existing({"kind": "x"}, _proc(pid=999)) is False


def test_should_claim_when_python_but_not_supervisor_cmdline():
    proc = _proc(pid=999, name="python.exe", cmdline="python -m something.else")
    assert s.should_yield_to_existing(_LOCK, proc) is False


# --------------------------------------------------------------------------
# build_heartbeat
# --------------------------------------------------------------------------


def test_build_heartbeat_has_required_fields():
    hb = s.build_heartbeat(s.SupervisorState(), s.Liveness.ALIVE, T0, 4242, 22148)
    for key in (
        "supervisor_pid",
        "updated_at",
        "state",
        "consecutive_failures",
        "restarts_in_window",
        "last_restart_at",
        "gateway_pid_observed",
        "gateway_alive",
    ):
        assert key in hb
    assert hb["supervisor_pid"] == 4242
    assert hb["gateway_pid_observed"] == 22148
    assert hb["gateway_alive"] is True
    assert hb["state"] == "watching"
    assert hb["updated_at"].endswith("+00:00")


def test_build_heartbeat_reflects_dead_gateway():
    hb = s.build_heartbeat(s.SupervisorState(), s.Liveness.DEAD, T0, 1, None)
    assert hb["gateway_alive"] is False
    assert hb["state"] == "restarting"


def test_build_heartbeat_shows_backoff_state():
    state = s.SupervisorState(consecutive_failures=2, last_restart_at=T0)
    hb = s.build_heartbeat(state, s.Liveness.ALIVE, T0 + timedelta(seconds=5), 1, 22148)
    assert hb["state"] == "backoff"


def test_build_heartbeat_shows_tripped_state():
    state = s.SupervisorState(tripped_until=T0 + timedelta(seconds=600))
    hb = s.build_heartbeat(state, s.Liveness.DEAD, T0, 1, None)
    assert hb["state"] == "tripped"


# --------------------------------------------------------------------------
# Injected boundaries (read_json, write_atomic) via tmp_path
# --------------------------------------------------------------------------


def test_read_json_missing_file_returns_none(tmp_path: Path):
    assert s.read_json(tmp_path / "nope.json") is None


def test_read_json_corrupt_returns_none(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert s.read_json(p) is None


def test_read_json_empty_returns_none(tmp_path: Path):
    p = tmp_path / "empty.json"
    p.write_text("   ", encoding="utf-8")
    assert s.read_json(p) is None


def test_read_json_non_object_returns_none(tmp_path: Path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert s.read_json(p) is None


def test_read_json_valid_object(tmp_path: Path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"pid": 5}), encoding="utf-8")
    assert s.read_json(p) == {"pid": 5}


def test_write_atomic_roundtrips(tmp_path: Path):
    p = tmp_path / "sub" / "hb.json"
    s.write_atomic(p, json.dumps({"a": 1}))
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    # No leftover temp files in the directory.
    assert [f.name for f in p.parent.iterdir()] == ["hb.json"]


# --------------------------------------------------------------------------
# Config.from_env
# --------------------------------------------------------------------------


def test_config_from_env_derives_paths():
    cfg = s.Config.from_env({"HERMES_HOME": "C:\\hh"})
    assert cfg.hermes_home == Path("C:\\hh")
    assert cfg.pid_path == Path("C:\\hh") / "gateway.pid"
    assert cfg.gateway_cmd_path == Path("C:\\hh") / "gateway-service" / "Hermes_Gateway.cmd"
    assert cfg.heartbeat_path == Path("C:\\hh") / "logs" / "supervisor.heartbeat.json"


def test_config_from_env_falls_back_without_hermes_home():
    cfg = s.Config.from_env({})
    assert cfg.hermes_home == Path(s.FALLBACK_HERMES_HOME)


def test_apply_env_overrides_sets_poll(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(s, "POLL_SECONDS", 30)
    s.apply_env_overrides({"SUPERVISOR_POLL_SECONDS": "7"})
    assert s.POLL_SECONDS == 7


def test_apply_env_overrides_ignores_non_integer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(s, "CB_MAX", 5)
    s.apply_env_overrides({"SUPERVISOR_CB_MAX": "abc"})
    assert s.CB_MAX == 5


def test_apply_env_overrides_defaults_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(s, "CB_COOLDOWN_SECONDS", 1800)
    s.apply_env_overrides({})
    assert s.CB_COOLDOWN_SECONDS == 1800


# --------------------------------------------------------------------------
# Cycle orchestration with fully faked boundaries
# --------------------------------------------------------------------------


def _fake_boundaries(
    *,
    pid_record: dict | None,
    proc: s.ProcessInfo | None,
    moment: datetime = T0,
) -> tuple[s.Boundaries, dict]:
    """Boundaries that serve a fixed observation and record side effects."""
    calls: dict = {"launched": 0, "written": [], "slept": []}

    def fake_read(path: Path) -> dict | None:
        if path.name == "gateway.pid":
            return pid_record
        return None

    def fake_find(pid: int) -> s.ProcessInfo | None:
        return proc

    def fake_launch(cmd: Path) -> None:
        calls["launched"] += 1

    def fake_write(path: Path, data: str) -> None:
        calls["written"].append((path.name, data))

    def fake_sleep(secs: float) -> None:
        calls["slept"].append(secs)

    bnd = s.Boundaries(
        read_json=fake_read,
        find_process=fake_find,
        launch_detached=fake_launch,
        write_atomic=fake_write,
        now=lambda: moment,
        sleep=fake_sleep,
    )
    return bnd, calls


def test_run_cycle_alive_writes_heartbeat_and_does_not_launch(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=_proc(cmdline=_GATEWAY_CMDLINE))
    s.run_cycle(cfg, s.SupervisorState(), bnd, dry_run=False)
    assert calls["launched"] == 0
    assert any(name == "supervisor.heartbeat.json" for name, _ in calls["written"])


def test_run_cycle_dead_launches_gateway(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    # Dead: no process at recorded pid.
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=None)
    s.run_cycle(cfg, s.SupervisorState(), bnd, dry_run=False)
    assert calls["launched"] == 1


def test_run_cycle_dry_run_never_launches(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=None)
    s.run_cycle(cfg, s.SupervisorState(), bnd, dry_run=True)
    assert calls["launched"] == 0


def test_perform_restart_aborts_when_gateway_already_alive(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    # find_process returns a live gateway -> re-check says ALIVE -> no launch.
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=_proc(cmdline=_GATEWAY_CMDLINE))
    s._perform_restart(cfg, bnd, s.SupervisorState().record_restart(T0))
    assert calls["launched"] == 0


def test_perform_restart_swallows_launch_error(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=None)

    def boom(cmd: Path) -> None:
        raise OSError("cannot spawn")

    bnd.launch_detached = boom
    # Must not propagate; returns the state it was given.
    prior = s.SupervisorState().record_restart(T0)
    assert s._perform_restart(cfg, bnd, prior) is prior


def test_perform_restart_confirms_when_alive_after_grace(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    # Sequenced find_process: dead on pre-check, alive after the launch grace.
    seq = [None, s.ProcessInfo(22148, "python.exe", _GATEWAY_CMDLINE)]
    launched: list[int] = []

    def fake_read(path: Path) -> dict | None:
        return _PID_RECORD if path.name == "gateway.pid" else None

    def fake_find(pid: int) -> s.ProcessInfo | None:
        return seq.pop(0) if seq else s.ProcessInfo(22148, "python.exe", _GATEWAY_CMDLINE)

    bnd = s.Boundaries(
        read_json=fake_read,
        find_process=fake_find,
        launch_detached=lambda cmd: launched.append(1),
        write_atomic=lambda path, data: None,
        now=lambda: T0,
        sleep=lambda secs: None,
    )
    s._perform_restart(cfg, bnd, s.SupervisorState().record_restart(T0))
    assert launched == [1]


def test_run_cycle_survives_heartbeat_write_failure(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    bnd, calls = _fake_boundaries(pid_record=_PID_RECORD, proc=_proc(cmdline=_GATEWAY_CMDLINE))

    def failing_write(path: Path, data: str) -> None:
        raise OSError("disk full")

    bnd.write_atomic = failing_write
    # Should not raise despite the heartbeat write failing.
    s.run_cycle(cfg, s.SupervisorState(), bnd, dry_run=False)


def test_acquire_single_instance_claims_when_no_lock(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    written: list[str] = []
    bnd = s.Boundaries(
        read_json=lambda path: None,
        find_process=lambda pid: None,
        launch_detached=lambda cmd: None,
        write_atomic=lambda path, data: written.append(path.name),
        now=lambda: T0,
        sleep=lambda secs: None,
    )
    assert s.acquire_single_instance(cfg, bnd) is True
    assert "supervisor.lock" in written


def test_acquire_single_instance_claims_stale_lock(tmp_path: Path):
    # Lock file exists but its pid resolves to no process -> claim it.
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    written: list[str] = []
    bnd = s.Boundaries(
        read_json=lambda path: {"pid": 999} if path.name == "supervisor.lock" else None,
        find_process=lambda pid: None,
        launch_detached=lambda cmd: None,
        write_atomic=lambda path, data: written.append(path.name),
        now=lambda: T0,
        sleep=lambda secs: None,
    )
    assert s.acquire_single_instance(cfg, bnd) is True
    assert "supervisor.lock" in written


def test_run_once_returns_zero(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    bnd, _ = _fake_boundaries(pid_record=_PID_RECORD, proc=_proc(cmdline=_GATEWAY_CMDLINE))
    assert s.run(cfg, bnd, once=True, dry_run=False) == 0


def test_run_exits_when_another_supervisor_holds_lock(tmp_path: Path):
    cfg = s.Config.from_env({"HERMES_HOME": str(tmp_path)})
    live_super = _proc(pid=999, name="pythonw.exe", cmdline="pythonw hermes_gateway_supervisor.py")

    def fake_read(path: Path) -> dict | None:
        if path.name == "supervisor.lock":
            return {"pid": 999}
        return None

    bnd = s.Boundaries(
        read_json=fake_read,
        find_process=lambda pid: live_super,
        launch_detached=lambda cmd: None,
        write_atomic=lambda path, data: None,
        now=lambda: T0,
        sleep=lambda secs: None,
    )
    # once=False path but single-instance guard should return 0 without looping.
    assert s.run(cfg, bnd, once=False, dry_run=False) == 0


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------


def test_parse_args_defaults():
    ns = s.parse_args([])
    assert ns.once is False
    assert ns.dry_run is False


def test_parse_args_flags():
    ns = s.parse_args(["--once", "--dry-run"])
    assert ns.once is True
    assert ns.dry_run is True
