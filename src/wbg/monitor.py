"""Bound one Linux analysis process group without changing the WSL VM."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from . import workflow
from .runtime import data_free_bytes
import shutil
import signal
import subprocess
import time


def _group_members(pgid: int) -> list[tuple[int, int]]:
    """Return (pid, RSS bytes) for this session's group, excluding zombies."""
    members = []
    page = os.sysconf("SC_PAGE_SIZE")
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            line = (path / "stat").read_text()
            fields = line[line.rfind(")") + 2:].split()
            if int(fields[2]) == pgid and int(fields[3]) == pgid and fields[0] != "Z":
                members.append((int(path.name), int(fields[21]) * page))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return members


def _tree_size(root: Path) -> int:
    total = 0
    for directory, _, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                pass
    return total


def _terminate(pgid: int, leader: subprocess.Popen) -> list[int]:
    """TERM then KILL only members of the newly created session."""
    if _group_members(pgid):
        os.killpg(pgid, signal.SIGTERM)
    try:
        leader.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    if _group_members(pgid):
        os.killpg(pgid, signal.SIGKILL)
    try:
        leader.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + 2
    remaining = [pid for pid, _ in _group_members(pgid)]
    while remaining and time.monotonic() < deadline:
        time.sleep(0.05)
        remaining = [pid for pid, _ in _group_members(pgid)]
    return remaining


def run(argv: list[str], *, run_root: Path, log_dir: Path, timeout_seconds: int | None,
        output_limit_mib: int, reserve_mib: int, cancel_marker: Path | None = None,
        env: dict[str, str] | None = None, budget_policy: dict | None = None) -> dict:
    """Run one fixed worker command; record measured limits and signal provenance."""
    if os.name != "posix" or not Path("/proc/self/stat").exists():
        raise RuntimeError("Linux /proc is required")
    if (timeout_seconds is not None and timeout_seconds <= 0) or output_limit_mib <= 0 or reserve_mib < 0:
        raise ValueError("invalid resource limits")
    if log_dir.exists():
        raise FileExistsError(log_dir)
    log_dir.mkdir(parents=True)
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.monotonic()
    requested_signal = None
    trigger = None
    peak_rss = 0
    rss_samples = 0
    last_disk = 0.0
    last_output_bytes = None
    last_work_free = None
    last_data_free = None
    leader = None
    previous_handlers = {}
    workflow_state = {}
    low_memory_samples = 0

    def on_signal(number, _frame):
        nonlocal requested_signal
        requested_signal = number

    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[number] = signal.getsignal(number)
            signal.signal(number, on_signal)
        with (log_dir / "stdout.log").open("xb") as stdout, (log_dir / "stderr.log").open("xb") as stderr:
            initial_output = _tree_size(run_root)
            try:
                data_free = data_free_bytes()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                data_free = None
                trigger = {"kind": "host_resource_unavailable", "detail": str(exc)}
            work_free = shutil.disk_usage(run_root).free
            if trigger is None and (initial_output >= output_limit_mib * 2**20 or
                    data_free <= reserve_mib * 2**20 or work_free <= reserve_mib * 2**20):
                trigger = {"kind": "initial_disk_gate", "output_bytes": initial_output,
                           "data_free_bytes": data_free, "work_free_bytes": work_free}
            if trigger is None:
                leader = subprocess.Popen(argv, stdout=stdout, stderr=stderr,
                                          env=env, start_new_session=True)
                pgid = leader.pid
                while leader.poll() is None:
                    now = time.monotonic()
                    elapsed = now - started
                    members = _group_members(pgid)
                    peak_rss = max(peak_rss, sum(rss for _, rss in members))
                    rss_samples += 1
                    from .protocol import atomic_json
                    atomic_json(run_root / "resource-progress.json", {
                        "elapsed_seconds": elapsed, "rss_sum_sampled_max_bytes": peak_rss,
                        "rss_samples": rss_samples, "process_group": pgid,
                        "scope": "sampled process group RSS sum; not an exact peak"})
                    if cancel_marker and cancel_marker.is_file():
                        trigger = {"kind": "explicit_cancel_marker", "marker": str(cancel_marker)}
                    elif requested_signal == signal.SIGINT:
                        trigger = {"kind": "terminal_sigint", "signal": int(requested_signal)}
                    elif requested_signal is not None:
                        trigger = {"kind": "external_signal", "signal": int(requested_signal)}
                    elif timeout_seconds is not None and elapsed >= timeout_seconds + workflow_state.get("additional_seconds", 0):
                        trigger = {"kind": "timeout", "elapsed_seconds": elapsed}
                    if trigger is None and budget_policy is not None:
                        probe_timeout = budget_policy.get("probe_timeout_seconds")
                        if not (run_root / "estimate.json").exists() and probe_timeout is not None and elapsed >= probe_timeout:
                            trigger = {"kind": "probe_timeout", "elapsed_seconds": elapsed}
                        else:
                            trigger = workflow.tick(run_root, workflow_state, budget_policy, now,
                                                    started + timeout_seconds + workflow_state.get("additional_seconds", 0) if timeout_seconds is not None else None)
                        from .resource_advice import memory_info
                        measured_memory = memory_info()
                        available = measured_memory.get("EffectiveMemAvailable", measured_memory.get("MemAvailable"))
                        low_memory_samples = low_memory_samples + 1 if available is not None and available < 512 * 2**20 else 0
                        if trigger is None and low_memory_samples >= 3:
                            trigger = {"kind": "memory_reserve", "available_bytes": available,
                                       "scope": "low effective runtime available memory; not an OOM diagnosis"}
                    if trigger is None and now - last_disk >= 5:
                        last_output_bytes = _tree_size(run_root)
                        last_work_free = shutil.disk_usage(run_root).free
                        try:
                            last_data_free = data_free_bytes()
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            trigger = {"kind": "host_resource_unavailable", "detail": str(exc)}
                        last_disk = now
                        if trigger is None:
                            if last_output_bytes >= output_limit_mib * 2**20:
                                trigger = {"kind": "output_limit", "output_bytes": last_output_bytes}
                            elif last_work_free <= reserve_mib * 2**20:
                                trigger = {"kind": "work_volume_reserve", "free_bytes": last_work_free}
                            elif last_data_free <= reserve_mib * 2**20:
                                trigger = {"kind": "data_volume_reserve", "free_bytes": last_data_free}
                    if trigger:
                        break
                    time.sleep(min(1.0, max(0.01, timeout_seconds + workflow_state.get("additional_seconds", 0) - elapsed)) if timeout_seconds is not None else 1.0)
                if trigger:
                    remaining = _terminate(pgid, leader)
                else:
                    remaining = [pid for pid, _ in _group_members(pgid)]
                    if remaining:
                        trigger = {"kind": "orphaned_group_members", "pids": remaining}
                        remaining = _terminate(pgid, leader)
                if remaining:
                    trigger = {"kind": "cleanup_incomplete", "prior_trigger": trigger,
                               "remaining_pids": remaining}
    except Exception:
        if leader and _group_members(leader.pid):
            _terminate(leader.pid, leader)
        raise
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
    total_elapsed = time.monotonic() - started
    waited = workflow.waiting_seconds(run_root, time.monotonic())
    return {"argv": argv, "started_at": started_utc,
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "boot_id": boot_id, "process_group": leader.pid if leader else None,
            "exit_code": leader.returncode if leader else None, "trigger": trigger,
            "elapsed_seconds": round(total_elapsed, 3),
            "waiting_seconds": round(waited, 3), "compute_seconds": round(max(0, total_elapsed - waited), 3),
            "rss_sum_sampled_max_bytes": peak_rss if rss_samples else None,
            "rss_samples": rss_samples, "sample_interval_seconds": 1,
            "initial_timeout_seconds": timeout_seconds,
            "explicit_additional_seconds": workflow_state.get("additional_seconds", 0),
            "disk_interval_seconds": 5, "last_output_bytes": last_output_bytes,
            "last_work_free_bytes": last_work_free, "last_data_free_bytes": last_data_free,
            "scope": "one newly created Linux session; RSS sum is sampled, not an exact peak or hard memory quota"}
