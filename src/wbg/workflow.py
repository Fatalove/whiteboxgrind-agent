"""Small, file-based estimate/decision protocol owned by the existing supervisor.

Quotes concern completion of this analysis attempt, never guaranteed recovery.
Detailed pilot accounting remains in commands.json and resource.json.
"""
from __future__ import annotations

import json
import fcntl
from contextlib import contextmanager
import math
import os
from pathlib import Path
import re
import secrets
import time

from .protocol import atomic_json

DEFAULTS = {"probe_timeout_seconds": None, "decision_wait_seconds": None, "overrun_grace_seconds": None}
PROTOCOL = "interactive-boundaries-v2"
STAGES = ("raw-collect", "formal-filter", "formal-unique", "formal-leakage", "formal-cpa")


def read(run: Path, name: str, default=None):
    path = run / name
    return json.loads(path.read_text()) if path.is_file() else default


@contextmanager
def locked(run: Path):
    with (run / ".workflow.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def enter_stage(run: Path, name: str, require_formal: bool = False):
    """Commit a stage or wait; same lock as checkpoint publication avoids races."""
    while True:
        with locked(run):
            state = read(run, "workflow-state.json", {})
            blocked = bool(state.get("pending")) or (require_formal and not (run / "formal-authorized.json").exists())
            boundary = read(run, "boundary-state.json", {"waiting": False, "waited_seconds": 0})
            now = time.monotonic()
            if blocked:
                if not boundary["waiting"]:
                    boundary.update(waiting=True, started_monotonic=now, next_stage=name)
                    atomic_json(run / "boundary-state.json", boundary)
            else:
                if boundary["waiting"]:
                    boundary["waited_seconds"] += now - boundary["started_monotonic"]
                    boundary.update(waiting=False, next_stage=None)
                    atomic_json(run / "boundary-state.json", boundary)
                atomic_json(run / "stage.json", {"stage": name, "at_monotonic": now})
                return
        time.sleep(0.1)


def waiting_seconds(run: Path, now: float) -> float:
    boundary = read(run, "boundary-state.json", {})
    return boundary.get("waited_seconds", 0) + (max(0, now - boundary["started_monotonic"]) if boundary.get("waiting") else 0)


def quote(commands: list[dict], pilot_count: int, formal_count: int, pilot_bytes: int,
          occupied_bytes: int, output_limit_bytes: int) -> dict:
    measured = {row["name"]: row["elapsed_seconds"] for row in commands}
    ratio = formal_count / pilot_count
    components = []
    for name, suffix in zip(STAGES, ("collect", "filter", "unique", "leakage", "cpa")):
        value = measured["pilot-" + suffix]
        # One scale cannot identify fixed overhead. Expose a planning range,
        # rather than inventing a fitted fixed/linear model or a confidence bound.
        low = value * ratio * 0.8 if suffix == "collect" else value * 0.8
        high = value * ratio * 1.5
        components.append({"stage": name, "seconds_low": low, "seconds_high": high})
    components.append({"stage": "validation_and_delivery", "seconds_low": 0, "seconds_high": 60})
    space = math.ceil(2 * ratio * pilot_bytes + 64 * 2**20)
    return {"schema_version": 1, "scope": "remaining full formal analysis and validation attempt",
            "formal_count": formal_count, "stages": components,
            "remaining_seconds": {"low": math.floor(sum(r["seconds_low"] for r in components)),
                                  "high": math.ceil(sum(r["seconds_high"] for r in components))},
            "space": {"estimated_additional_bytes": space, "occupied_bytes": occupied_bytes,
                      "authorized_output_limit_bytes": output_limit_bytes,
                      "estimate_exceeds_allowance": occupied_bytes + space > output_limit_bytes},
            "uncertainty": "single-scale heuristic planning range, not a confidence interval or upper bound; feature growth unknown",
            "recovery_guaranteed": False}


def remaining(run: Path, estimate: dict, now: float) -> tuple[dict | None, dict]:
    stage = read(run, "stage.json", {})
    name = stage.get("stage", "preflight")
    progress = {"stage": name, "completed": None, "total": None}
    if name == "awaiting_formal_approval":
        return estimate["remaining_seconds"], progress
    items = estimate["stages"]
    names = [row["stage"] for row in items]
    finished = {r["name"] for r in read(run, "commands.json", {"commands": []})["commands"]}
    if name in names:
        index = names.index(name) + (1 if name in finished else 0)
    elif name.startswith("formal-"):
        # Read/semantic checks occur between native stages; do not claim a
        # percentage for checks or native CPA when none is observable.
        index = next((i for i, n in enumerate(STAGES) if n not in finished), len(STAGES))
    elif name.startswith("holdout") or name == "independent_holdout":
        index = len(STAGES)
    else:
        return estimate["remaining_seconds"], progress
    active = items[index]
    # Checks between native stages must not subtract time from a stage that
    # has not started. Their cost remains part of the coarse delivery margin.
    validation_active = name.startswith("holdout") or name == "independent_holdout"
    elapsed = max(0, now - stage.get("at_monotonic", now)) if name == active["stage"] or validation_active else 0
    low = max(0, active["seconds_low"] - elapsed)
    high = max(0, active["seconds_high"] - elapsed)
    if name == "raw-collect" and name not in finished:
        log = run / "logs/raw-collect/stdout.log"
        # The tracer prints an input before starting it. Only its predecessor
        # is known completed; never call the just-started row completed.
        numbers = re.findall(r"(?m)^(\d+): [0-9a-f]{32}\s*$", log.read_text(errors="replace")) if log.exists() else []
        completed = max(0, int(numbers[-1]) - 1) if numbers else 0
        total = estimate["formal_count"]
        progress.update(completed=min(completed, total), total=total)
        if completed >= 2:
            seconds = elapsed / completed * (total - completed)
            low, high = seconds * 0.8, seconds * 1.5
    elif name == "raw-collect":
        progress.update(completed=estimate["formal_count"], total=estimate["formal_count"])
    elif elapsed > active["seconds_high"]:
        return None, progress  # Unknown is better than a fabricated countdown.
    return {"low": math.floor(low + sum(r["seconds_low"] for r in items[index + 1:])),
            "high": math.ceil(high + sum(r["seconds_high"] for r in items[index + 1:]))}, progress


def tick(run: Path, state: dict, policy: dict, now: float, hard_deadline: float | None) -> dict | None:
    with locked(run):
        return _tick(run, state, policy, now, hard_deadline)


def _tick(run: Path, state: dict, policy: dict, now: float, hard_deadline: float | None):
    estimate = read(run, "estimate.json")
    if estimate is None:
        return None
    left, progress = remaining(run, estimate, now)
    pending = state.get("pending")
    if pending:
        answer = read(run, "decisions/" + pending["checkpoint_id"] + ".json")
        if answer and answer.get("checkpoint_id") == pending["checkpoint_id"]:
            if answer.get("choice") == "stop":
                return {"kind": "approval_declined", "checkpoint_id": pending["checkpoint_id"]}
            if answer.get("choice") != "continue":
                raise ValueError("invalid workflow decision")
            if pending["deadline_monotonic"] is not None and now >= pending["deadline_monotonic"]:
                return {"kind": "approval_timeout", "checkpoint_id": pending["checkpoint_id"]}
            extra = answer.get("additional_seconds", 0)
            approval = answer.get("approval_quote")
            if type(extra) is not int or not 0 <= extra <= 86400 or (extra and not approval):
                raise ValueError("invalid explicit time extension")
            if extra:
                if hard_deadline is None:
                    raise ValueError("unbounded timing does not require an extension")
                state["additional_seconds"] = state.get("additional_seconds", 0) + extra
                hard_deadline += extra
                extension = {"checkpoint_id": pending["checkpoint_id"], "additional_seconds": extra,
                             "approval_quote": approval, "approved_by": "user", "at_monotonic": now}
                extensions = read(run, "budget-extensions.json", {"extensions": []})
                extensions["extensions"].append(extension)
                atomic_json(run / "budget-extensions.json", extensions)
                group = read(run, "budget-group.json")
                if group:
                    group["group_max_seconds"] += extra
                    group.setdefault("explicit_extensions", []).append(extension)
                    atomic_json(run / "budget-group.json", group)
            state.setdefault("decisions", []).append({**pending, "choice": "continue", "at_monotonic": now})
            if not state.get("formal_authorized"):
                state["formal_authorized"] = True
                atomic_json(run / "formal-authorized.json", {"checkpoint_id": pending["checkpoint_id"]})
            # Continuation uses the remaining allowance plus any explicit grant.
            # If no useful ETA exists, ask again after one decision interval.
            state["expected_at"] = now + max(1, left["high"]) if left else None
            state["pending"] = pending = None
        elif pending["deadline_monotonic"] is not None and now >= pending["deadline_monotonic"]:
            return {"kind": "approval_timeout", "checkpoint_id": pending["checkpoint_id"]}
    if (state.get("formal_authorized") and state.get("expected_at") is None and
            state.get("last_stage") != progress["stage"] and left):
        state["expected_at"] = now + max(1, left["high"])
    if not pending and (not state.get("formal_authorized") or
                        (state.get("expected_at") is not None and now >= state["expected_at"])):
        reason = "formal_approval" if not state.get("formal_authorized") else "estimate_overrun"
        window = policy["decision_wait_seconds"] if reason == "formal_approval" else policy["overrun_grace_seconds"]
        deadline = now + window if window is not None else None
        if hard_deadline is not None:
            deadline = min(hard_deadline, deadline) if deadline is not None else hard_deadline
        pending = {"checkpoint_id": secrets.token_hex(16), "reason": reason,
                   "deadline_monotonic": deadline}
        state["pending"] = pending
    state["last_stage"] = progress["stage"]
    boundary = read(run, "boundary-state.json", {})
    view = {"schema_version": 1, "run_id": run.name,
            "status": "awaiting_decision" if pending else "running", "progress": progress,
            "estimated_remaining_seconds": left, "estimate_scope": estimate["scope"],
            "recovery_guaranteed": False, "space": estimate["space"],
            "protocol": PROTOCOL, "waiting_at_boundary": bool(boundary.get("waiting")),
            "next_stage": boundary.get("next_stage"),
            "authorized_remaining_seconds": max(0, math.floor(hard_deadline - now)) if hard_deadline is not None else None,
            "decision": ({"checkpoint_id": pending["checkpoint_id"], "reason": pending["reason"],
                          "reply_within_seconds": max(0, math.floor(pending["deadline_monotonic"] - now)) if pending["deadline_monotonic"] is not None else None,
                          "deadline_monotonic": pending["deadline_monotonic"],
                          "choices": ["continue", "stop"]} if pending else None)}
    atomic_json(run / "workflow-state.json", state)
    atomic_json(run / "progress.json", view)
    return None


def decide(run: Path, checkpoint_id: str, choice: str, additional_seconds: int = 0,
           approval_quote: str | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id) or choice not in {"continue", "stop"}:
        raise ValueError("invalid decision")
    if (type(additional_seconds) is not int or not 0 <= additional_seconds <= 86400 or
            (additional_seconds and (choice != "continue" or not isinstance(approval_quote, str) or
                                     not approval_quote.strip()))):
        raise ValueError("time extension requires continue and an explicit user approval quote")
    view = read(run, "progress.json", {})
    pending = view.get("decision") or {}
    if (read(run, "result.json") or view.get("status") != "awaiting_decision" or
            checkpoint_id != pending.get("checkpoint_id") or
            (pending.get("deadline_monotonic") is not None and time.monotonic() >= pending["deadline_monotonic"])):
        raise ValueError("checkpoint is stale, expired, or not awaiting a decision")
    if additional_seconds and view.get("authorized_remaining_seconds") is None:
        raise ValueError("no time extension is needed in user-controlled timing mode")
    path = run / "decisions" / (checkpoint_id + ".json")
    path.parent.mkdir(exist_ok=True)
    # First answer wins; concurrent/replayed decisions cannot overwrite it.
    payload = {"checkpoint_id": checkpoint_id, "choice": choice,
               "additional_seconds": additional_seconds, "approval_quote": approval_quote}
    temporary = path.with_name("." + checkpoint_id + "-" + secrets.token_hex(8) + ".json")
    try:
        atomic_json(temporary, payload)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"schema_version": 1, "status": "accepted", **payload,
            "budget_extension_requested_seconds": additional_seconds}
