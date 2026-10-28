"""Rebuild a minimal, key-free history from immutable run evidence."""

import json
from pathlib import Path
import yaml

from .execution import _atomic_text


def _read(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def identity_alive(marker: dict) -> bool:
    try:
        if marker["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
            return False
        stat = Path(f"/proc/{int(marker['pid'])}/stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        return fields[0] != "Z" and int(fields[19]) == marker["start_ticks"]
    except (KeyError, OSError, ValueError):
        return False


def summarize(run: Path, active: dict | None = None) -> dict:
    result = _read(run / "result.json")
    config = _read(run / "effective-config.json") or _read(run / "requested-config.json") or {}
    if not config and (run / "config.yaml").is_file():
        config = yaml.safe_load((run / "config.yaml").read_text()) or {}
    experiment = config.get("experiment", "ordinary-aes-legacy" if "stageA" in run.name else "unknown")
    kind = ("diagnostic" if "diagnostic" in experiment else
            "analysis" if experiment != "unknown" else "setup/preflight")
    if (_read(run / "operation.json") or {}).get("command") == "probe":
        kind = "diagnostic"
    row = {"run_id": run.name, "record_kind": kind, "experiment": experiment,
           "evidence_root": str(run), "protocol": "stage-b" if "stageB" in run.name else "legacy-a",
           "target_sha256": config.get("target", {}).get("sha256"),
           "seed": config.get("inputs", {}).get("seed"),
           "trace_count": config.get("inputs", {}).get("trace_count"),
           "analysis": config.get("analysis"), "environment_lock": str(run / "source-lock.json") if (run / "source-lock.json").is_file() else None}
    if result is None:
        live = active and active.get("run_id") == run.name and identity_alive(active)
        row.update(status="incomplete", reason_code="active" if live else "unfinished",
                   execution="running" if live else "unknown", recovery="unknown")
        return row
    recovery = result.get("recovery", "unknown")
    execution = result.get("execution", result.get("engineering", "unknown"))
    resource = _read(run / "resource.json") or {}
    row.update(status=result.get("status", "unknown"), reason_code=result.get("reason_code"),
               execution=execution.get("status", "unknown") if isinstance(execution, dict) else execution,
               recovery=recovery.get("status", "unknown") if isinstance(recovery, dict) else recovery,
               elapsed_seconds=resource.get("elapsed_seconds", result.get("analysis_elapsed_seconds")),
               sampled_rss_sum_max_bytes=resource.get("rss_sum_sampled_max_bytes"))
    return row


def rebuild(runs: Path, output: Path, active_path: Path | None = None, catalog: dict | None = None) -> dict:
    active = _read(active_path) if active_path else None
    records = []
    for run in sorted(runs.iterdir()):
        if not run.is_dir():
            continue
        try:
            row = summarize(run, active)
            if catalog and run.name in catalog:
                row.update(catalog[run.name])
            records.append(row)
        except (ValueError, OSError) as exc:
            records.append({"run_id": run.name, "record_kind": "unknown", "status": "incomplete",
                            "reason_code": "unreadable_evidence", "detail": type(exc).__name__})
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records)
    _atomic_text(output, text)
    return {"records": len(records), "output": str(output),
            "counts": {status: sum(row["status"] == status for row in records)
                       for status in sorted({row["status"] for row in records})},
            "scope": "all observed terminal statuses; recovery rates require explicit analysis denominators"}
