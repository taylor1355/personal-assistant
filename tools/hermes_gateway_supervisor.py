#!/usr/bin/env python3
"""Hermes gateway crash-restart watchdog (PA-104).

The live Hermes gateway is launched by a Startup-folder shortcut that fires
only AT LOGIN. When the gateway crashes mid-session nothing relaunches it, so a
2026-06-30 crash left it DOWN ~12h. This supervisor watches gateway liveness
continuously and relaunches it on death, cause-agnostic.

Design: every DECISION is a pure function (`classify_liveness`,
`decide_next_action`, `should_yield_to_existing`, `build_heartbeat`); every
OS-touching call is an INJECTED boundary (`read_json`, `find_process`,
`launch_detached`, `write_atomic`, `now`). That split keeps the module
importable on Linux/CI (where the unit suite runs) — the Windows-only
`subprocess` creationflags live inside the boundary functions as plain int
constants, never behind a `msvcrt`/win32 import.

Liveness facts baked into the predicate (verified against the live box, see
PA-104):
  - The RUNNING gateway image resolves to `python.exe` (uv cpython) even though
    the .cmd launches `pythonw.exe`. So the predicate accepts BOTH images and
    matches on the COMMAND LINE, not the image name.
  - `gateway.pid` / `gateway.lock` carry `start_time: null`, so PID reuse can't
    be disambiguated by start time — we re-check the live cmdline instead.
  - `gateway_state.json` is EVENT-DRIVEN (its `updated_at` went 8 days stale
    while the gateway was alive), so it is NEVER used for liveness.

The install helper (`install_hermes_supervisor.ps1`) registers this under
pythonw so it runs without a console window. This module is stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

logger = logging.getLogger("hermes_gateway_supervisor")

# --------------------------------------------------------------------------
# Windows process-creation flags (plain ints so the module imports on Linux).
# Only ever passed to subprocess.Popen inside launch_detached, which is only
# invoked on the live Windows box.
# --------------------------------------------------------------------------
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# --------------------------------------------------------------------------
# Tunables. Each overridable via a SUPERVISOR_* env var (see Config).
# --------------------------------------------------------------------------
POLL_SECONDS = 30
# How long a restarted gateway must stay alive before we forgive prior failures.
STABILIZE_SECONDS = 60
# Circuit breaker: at most CB_MAX restarts within CB_WINDOW before we trip.
CB_WINDOW_SECONDS = 15 * 60
CB_MAX = 5
CB_COOLDOWN_SECONDS = 30 * 60
# Post-restart backoff schedule, indexed by (consecutive_failures - 1), capped.
BACKOFF_SECONDS = [5, 15, 60, 300]
# Grace period after launch before we confirm a new matching process appeared.
RESTART_GRACE_SECONDS = 10

# Fallback when HERMES_HOME is unset. A WARNING is logged when this is used.
FALLBACK_HERMES_HOME = r"C:\Users\taylor\Dev\hermes-home"

# Marker substring identifying THIS supervisor's own process in a cmdline.
SUPERVISOR_MARKER = "hermes_gateway_supervisor.py"

# Log-file rotation.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


# --------------------------------------------------------------------------
# Pure data types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessInfo:
    """A live OS process, as observed via find_process."""

    pid: int
    name: str
    cmdline: str


class Liveness(Enum):
    ALIVE = "alive"
    DEAD = "dead"
    AMBIGUOUS = "ambiguous"


class ActionKind(Enum):
    SLEEP = "sleep"
    RESTART = "restart"
    TRIPPED_WAIT = "tripped_wait"


@dataclass(frozen=True)
class Action:
    """A decision the loop should carry out.

    - SLEEP: gateway healthy; wait `seconds` then re-check.
    - RESTART: gateway dead; relaunch, then wait `seconds` (post-launch backoff).
    - TRIPPED_WAIT: circuit breaker open; wait `seconds` without launching.
    """

    kind: ActionKind
    seconds: float


@dataclass(frozen=True)
class SupervisorState:
    """Immutable restart bookkeeping. Updated via the helper methods below."""

    consecutive_failures: int = 0
    restart_times: tuple[datetime, ...] = ()
    last_restart_at: datetime | None = None
    tripped_until: datetime | None = None

    def reset_failures(self) -> SupervisorState:
        return replace(
            self,
            consecutive_failures=0,
            last_restart_at=None,
        )

    def record_restart(self, now: datetime) -> SupervisorState:
        return replace(
            self,
            consecutive_failures=self.consecutive_failures + 1,
            restart_times=self.restart_times + (now,),
            last_restart_at=now,
        )

    def trip(self, until: datetime) -> SupervisorState:
        return replace(self, tripped_until=until)

    def restarts_within(self, now: datetime, window_seconds: float) -> int:
        cutoff = now.timestamp() - window_seconds
        return sum(1 for t in self.restart_times if t.timestamp() >= cutoff)


# --------------------------------------------------------------------------
# Pure logic
# --------------------------------------------------------------------------


def is_gateway_process(proc: ProcessInfo, pid_record: dict | None) -> bool:
    """True when `proc` is the Hermes gateway.

    Matches on image name (python.exe OR pythonw.exe — see module docstring)
    AND command line. A command line qualifies if it names the hermes gateway
    invocation directly, OR if it contains the main.py path recorded in the
    pidfile's argv.
    """
    if proc.name.lower() not in {"python.exe", "pythonw.exe"}:
        return False

    cmd = proc.cmdline or ""
    if "hermes_cli" in cmd and "gateway run" in cmd:
        return True

    # Fall back to the recorded argv main.py path (e.g. "...hermes_cli\main.py").
    if pid_record:
        argv = pid_record.get("argv")
        if isinstance(argv, list):
            for token in argv:
                if (
                    isinstance(token, str)
                    and token.endswith("main.py")
                    and "hermes_cli" in token
                    and token in cmd
                ):
                    return True
    return False


def classify_liveness(pid_record: dict | None, proc: ProcessInfo | None) -> Liveness:
    """Decide whether the recorded gateway PID is a live gateway.

    DEAD (restart-warranted) when there is no usable pidfile, no process at the
    recorded PID, or a DIFFERENT process reused that PID. AMBIGUOUS (do-not-
    restart) only when the image name matches but the cmdline is unreadable —
    restarting on an unreadable cmdline risks double-launching a healthy gateway.
    """
    if not pid_record or not isinstance(pid_record.get("pid"), int):
        logger.warning("classified DEAD — missing or unparseable pidfile")
        return Liveness.DEAD

    if proc is None:
        logger.info("classified DEAD — no process at recorded pid %s", pid_record.get("pid"))
        return Liveness.DEAD

    if is_gateway_process(proc, pid_record):
        return Liveness.ALIVE

    name_matches = proc.name.lower() in {"python.exe", "pythonw.exe"}
    if name_matches and not (proc.cmdline or "").strip():
        logger.warning(
            "classified AMBIGUOUS — pid %s is %s with unreadable cmdline; not restarting",
            proc.pid,
            proc.name,
        )
        return Liveness.AMBIGUOUS

    logger.warning(
        "classified DEAD — pid %s reused by unrelated process %s (cmdline=%r)",
        proc.pid,
        proc.name,
        proc.cmdline,
    )
    return Liveness.DEAD


def decide_next_action(
    state: SupervisorState,
    liveness: Liveness,
    now: datetime,
) -> tuple[Action, SupervisorState]:
    """Pure state machine: current state + liveness -> (action, next state).

    - Healthy (ALIVE/AMBIGUOUS): SLEEP; forgive prior failures once the last
      restart has held for STABILIZE_SECONDS.
    - Tripped: TRIPPED_WAIT for the cooldown remainder, no launch.
    - DEAD: trip the breaker if this would exceed CB_MAX restarts in the
      window; otherwise record the restart and RESTART with backoff delay.
    """
    poll = float(POLL_SECONDS)

    if liveness in (Liveness.ALIVE, Liveness.AMBIGUOUS):
        new_state = state
        if state.last_restart_at is not None:
            held = now.timestamp() - state.last_restart_at.timestamp()
            if held >= STABILIZE_SECONDS:
                logger.info("gateway stabilized — resetting failure count")
                new_state = state.reset_failures()
        return Action(ActionKind.SLEEP, poll), new_state

    # liveness is DEAD from here.
    if state.tripped_until is not None and now < state.tripped_until:
        remaining = state.tripped_until.timestamp() - now.timestamp()
        return Action(ActionKind.TRIPPED_WAIT, max(0.0, remaining)), state

    # Cooldown expired (or never tripped): clear any stale trip and evaluate.
    working = state
    if working.tripped_until is not None:
        working = replace(working, tripped_until=None)

    # Count PRIOR restarts in the window; if we've already hit CB_MAX, the next
    # would be the (CB_MAX + 1)th — trip instead of launching.
    if working.restarts_within(now, CB_WINDOW_SECONDS) >= CB_MAX:
        until = datetime.fromtimestamp(
            now.timestamp() + CB_COOLDOWN_SECONDS, tz=timezone.utc
        )
        tripped_state = working.trip(until)
        logger.error(
            "circuit breaker TRIPPED — %d restarts within %ds; cooling down %ds",
            CB_MAX,
            CB_WINDOW_SECONDS,
            CB_COOLDOWN_SECONDS,
        )
        return Action(ActionKind.TRIPPED_WAIT, float(CB_COOLDOWN_SECONDS)), tripped_state

    new_state = working.record_restart(now)
    idx = min(new_state.consecutive_failures - 1, len(BACKOFF_SECONDS) - 1)
    delay = float(BACKOFF_SECONDS[idx])
    logger.info(
        "gateway DEAD — restart #%d, post-launch backoff %.0fs",
        new_state.consecutive_failures,
        delay,
    )
    return Action(ActionKind.RESTART, delay), new_state


def should_yield_to_existing(
    lock_record: dict | None,
    proc_of_lock_pid: ProcessInfo | None,
    my_marker: str = SUPERVISOR_MARKER,
) -> bool:
    """True when another live supervisor already holds the lock.

    Yields only when the lock's PID resolves to a live python/pythonw process
    whose cmdline contains the supervisor marker. A stale lock (no process) or a
    reused PID (unrelated process) is claimable.
    """
    if not lock_record or not isinstance(lock_record.get("pid"), int):
        return False
    if proc_of_lock_pid is None:
        return False
    if proc_of_lock_pid.name.lower() not in {"python.exe", "pythonw.exe"}:
        return False
    return my_marker in (proc_of_lock_pid.cmdline or "")


def _heartbeat_state_label(state: SupervisorState, liveness: Liveness, now: datetime) -> str:
    if state.tripped_until is not None and now < state.tripped_until:
        return "tripped"
    if liveness == Liveness.DEAD:
        return "restarting"
    if state.consecutive_failures > 0:
        return "backoff"
    return "watching"


def build_heartbeat(
    state: SupervisorState,
    liveness: Liveness,
    now: datetime,
    supervisor_pid: int,
    gateway_pid: int | None,
) -> dict:
    """Serializable heartbeat payload written atomically each loop iteration."""
    return {
        "supervisor_pid": supervisor_pid,
        "updated_at": now.astimezone(timezone.utc).isoformat(),
        "state": _heartbeat_state_label(state, liveness, now),
        "consecutive_failures": state.consecutive_failures,
        "restarts_in_window": state.restarts_within(now, CB_WINDOW_SECONDS),
        "last_restart_at": (
            state.last_restart_at.astimezone(timezone.utc).isoformat()
            if state.last_restart_at is not None
            else None
        ),
        "gateway_pid_observed": gateway_pid,
        "gateway_alive": liveness == Liveness.ALIVE,
    }


# --------------------------------------------------------------------------
# Injected boundaries (real implementations; overridable in tests)
# --------------------------------------------------------------------------


def read_json(path: Path) -> dict | None:
    """Tolerant JSON read: missing/empty/corrupt/non-object -> None."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def find_process(pid: int) -> ProcessInfo | None:
    """Resolve a PID to a ProcessInfo via PowerShell's CIM, or None if absent.

    Invokes `powershell` directly (no shell wrapper) and asks for a one-object
    JSON payload with Name + CommandLine. A missing process yields empty stdout
    -> None. CommandLine can be null for processes we can't introspect; that
    surfaces as an empty cmdline (classify_liveness treats it as AMBIGUOUS).
    """
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
        f"-ErrorAction SilentlyContinue | "
        f"Select-Object -First 1 Name, CommandLine; "
        f"if ($p) {{ $p | ConvertTo-Json -Compress }}"
    )
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("find_process failed to invoke powershell for pid %s: %s", pid, exc)
        return None

    out = (result.stdout or "").strip()
    if not out:
        return None
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        logger.warning("find_process could not parse powershell output for pid %s", pid)
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("Name") or ""
    cmdline = parsed.get("CommandLine") or ""
    return ProcessInfo(pid=pid, name=str(name), cmdline=str(cmdline))


def launch_detached(cmd_path: Path) -> None:
    """Launch the gateway .cmd fully detached (no console, own process group)."""
    subprocess.Popen(  # noqa: S603 — fixed, config-derived command path
        ["cmd.exe", "/c", str(cmd_path)],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def write_atomic(path: Path, data: str) -> None:
    """Write `data` to `path` atomically (tempfile in same dir + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def _env_int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring non-integer %s=%r; using %d", name, raw, default)
        return default


def apply_env_overrides(env: dict[str, str] | None = None) -> None:
    """Override the module-level tunables from SUPERVISOR_* env vars.

    The pure decision functions read these module globals directly (keeping
    their signatures small, per the plan), so an override has to mutate the
    globals. Called once at process start; one process per invocation makes
    module-level mutation safe here.
    """
    env = env if env is not None else dict(os.environ)
    global POLL_SECONDS, STABILIZE_SECONDS, CB_WINDOW_SECONDS, CB_MAX
    global CB_COOLDOWN_SECONDS, RESTART_GRACE_SECONDS
    POLL_SECONDS = _env_int(env, "SUPERVISOR_POLL_SECONDS", POLL_SECONDS)
    STABILIZE_SECONDS = _env_int(env, "SUPERVISOR_STABILIZE_SECONDS", STABILIZE_SECONDS)
    CB_WINDOW_SECONDS = _env_int(env, "SUPERVISOR_CB_WINDOW_SECONDS", CB_WINDOW_SECONDS)
    CB_MAX = _env_int(env, "SUPERVISOR_CB_MAX", CB_MAX)
    CB_COOLDOWN_SECONDS = _env_int(env, "SUPERVISOR_CB_COOLDOWN_SECONDS", CB_COOLDOWN_SECONDS)
    RESTART_GRACE_SECONDS = _env_int(
        env, "SUPERVISOR_RESTART_GRACE_SECONDS", RESTART_GRACE_SECONDS
    )


@dataclass(frozen=True)
class Config:
    """All derived paths, from HERMES_HOME. Tunables are module constants
    (overridable via apply_env_overrides)."""

    hermes_home: Path
    pid_path: Path
    lock_path: Path
    gateway_state_path: Path
    gateway_cmd_path: Path
    log_path: Path
    heartbeat_path: Path
    supervisor_lock_path: Path

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Config:
        env = environ if environ is not None else dict(os.environ)
        home_raw = env.get("HERMES_HOME")
        if not home_raw:
            logger.warning(
                "HERMES_HOME unset — falling back to %s", FALLBACK_HERMES_HOME
            )
            home_raw = FALLBACK_HERMES_HOME
        home = Path(home_raw)
        logs = home / "logs"
        return cls(
            hermes_home=home,
            pid_path=home / "gateway.pid",
            lock_path=home / "gateway.lock",
            gateway_state_path=home / "gateway_state.json",
            gateway_cmd_path=home / "gateway-service" / "Hermes_Gateway.cmd",
            log_path=logs / "supervisor.log",
            heartbeat_path=logs / "supervisor.heartbeat.json",
            supervisor_lock_path=logs / "supervisor.lock",
        )


# --------------------------------------------------------------------------
# Boundary bundle (lets run() and tests swap OS calls wholesale)
# --------------------------------------------------------------------------


@dataclass
class Boundaries:
    read_json: Callable[[Path], dict | None] = read_json
    find_process: Callable[[int], ProcessInfo | None] = find_process
    launch_detached: Callable[[Path], None] = launch_detached
    write_atomic: Callable[[Path, str], None] = write_atomic
    now: Callable[[], datetime] = now
    sleep: Callable[[float], None] = time.sleep


# --------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------


def configure_logging(log_path: Path, level: int = logging.INFO) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s supervisor: %(message)s")
    )
    root = logging.getLogger("hermes_gateway_supervisor")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    # Mirror to stderr so console --once/--dry-run runs surface output. Under
    # pythonw (the installed mode) sys.stderr is None, so guard the handler —
    # the rotating file handler above is the durable sink either way.
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("supervisor: %(message)s"))
        root.addHandler(stream)


# --------------------------------------------------------------------------
# Single-instance guard
# --------------------------------------------------------------------------


def acquire_single_instance(config: Config, bnd: Boundaries) -> bool:
    """Claim the supervisor lock. Returns False if another live one holds it."""
    lock_record = bnd.read_json(config.supervisor_lock_path)
    if lock_record is not None:
        lock_pid = lock_record.get("pid")
        proc = bnd.find_process(lock_pid) if isinstance(lock_pid, int) else None
        if should_yield_to_existing(lock_record, proc):
            logger.info("another supervisor holds the lock (pid %s) — exiting", lock_pid)
            return False
    bnd.write_atomic(
        config.supervisor_lock_path,
        json.dumps({"pid": os.getpid(), "kind": "hermes-gateway-supervisor"}),
    )
    return True


# --------------------------------------------------------------------------
# One check-decide-act cycle
# --------------------------------------------------------------------------


def _observe(config: Config, bnd: Boundaries) -> tuple[dict | None, ProcessInfo | None, int | None]:
    pid_record = bnd.read_json(config.pid_path)
    gateway_pid = pid_record.get("pid") if isinstance(pid_record, dict) else None
    proc = bnd.find_process(gateway_pid) if isinstance(gateway_pid, int) else None
    return pid_record, proc, gateway_pid if isinstance(gateway_pid, int) else None


def run_cycle(
    config: Config,
    state: SupervisorState,
    bnd: Boundaries,
    dry_run: bool,
) -> SupervisorState:
    """One check → decide → write-heartbeat → act cycle. Returns next state."""
    moment = bnd.now()
    pid_record, proc, gateway_pid = _observe(config, bnd)
    liveness = classify_liveness(pid_record, proc)
    action, next_state = decide_next_action(state, liveness, moment)

    if dry_run:
        logger.info(
            "dry-run observation — gateway_pid=%s liveness=%s next_action=%s",
            gateway_pid,
            liveness.value,
            action.kind.value,
        )

    heartbeat = build_heartbeat(next_state, liveness, moment, os.getpid(), gateway_pid)
    try:
        bnd.write_atomic(config.heartbeat_path, json.dumps(heartbeat, indent=2))
    except OSError as exc:
        logger.warning("heartbeat write failed: %s", exc)

    if action.kind == ActionKind.RESTART and not dry_run:
        next_state = _perform_restart(config, bnd, next_state)
    elif action.kind == ActionKind.RESTART and dry_run:
        logger.info("dry-run — would restart gateway (skipping launch)")

    if action.seconds > 0:
        bnd.sleep(action.seconds)
    return next_state


def _perform_restart(
    config: Config,
    bnd: Boundaries,
    state: SupervisorState,
) -> SupervisorState:
    """Re-verify death, launch, wait grace, confirm a matching process appeared."""
    # Re-verify liveness immediately before launching — the gateway may have
    # come back on its own (or another supervisor beat us to it).
    pid_record, proc, _ = _observe(config, bnd)
    if classify_liveness(pid_record, proc) == Liveness.ALIVE:
        logger.info("restart aborted — gateway already alive on re-check")
        return state

    logger.info("launching gateway via %s", config.gateway_cmd_path)
    try:
        bnd.launch_detached(config.gateway_cmd_path)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("launch failed: %s", exc)
        return state

    bnd.sleep(RESTART_GRACE_SECONDS)

    pid_record, proc, _ = _observe(config, bnd)
    if classify_liveness(pid_record, proc) == Liveness.ALIVE:
        logger.info("restart confirmed — gateway is alive")
    else:
        logger.warning("restart unconfirmed — no matching gateway process after grace")
    return state


# --------------------------------------------------------------------------
# Loop / entrypoint
# --------------------------------------------------------------------------


def run(
    config: Config,
    bnd: Boundaries | None = None,
    once: bool = False,
    dry_run: bool = False,
) -> int:
    """Main supervise loop. Returns a process exit code."""
    bnd = bnd or Boundaries()

    if not once and not acquire_single_instance(config, bnd):
        return 0

    state = SupervisorState()
    if once:
        run_cycle(config, state, bnd, dry_run)
        return 0

    while True:
        state = run_cycle(config, state, bnd, dry_run)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hermes_gateway_supervisor.py",
        description="Watchdog that relaunches the Hermes gateway when it dies.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check-decide-act cycle and exit (no loop).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and decide, but never launch the gateway.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    apply_env_overrides()
    config = Config.from_env()
    configure_logging(config.log_path)
    return run(config, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
