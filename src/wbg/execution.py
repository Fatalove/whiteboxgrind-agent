"""Own Stage B run identity, process supervision, terminal result and export."""

from __future__ import annotations

import copy
import base64
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile

from . import doctor, inputs, monitor
from .config import PROJECT, to_yaml
from .protocol import EXIT, atomic_json, response
from .budgets import authorization
from .runtime import BACKEND, WORK_ROOT


WORK = WORK_ROOT
DEFAULT_EXPORT = Path(os.environ.get("WBG_EXPORT_ROOT", str(WORK_ROOT / "exports")))
RESOURCES = PROJECT / "fixtures" / "stage-b-aes128" / "resources"
WRAPPERS = PROJECT / "fixtures" / "stage-b-aes128" / "wrappers"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _windows_location(path: Path) -> str | None:
    pieces = path.resolve().parts
    if len(pieces) >= 4 and pieces[1] == "mnt" and len(pieces[2]) == 1:
        return pieces[2].upper() + ":\\" + "\\".join(pieces[3:])
    return None


def _prepare(run: Path, requested: dict, effective: dict, environment: dict) -> None:
    snapshot = run / "orchestrator"
    sources = sorted((PROJECT / "src/wbg").glob("*.py")) + [PROJECT / "scripts/wbg", PROJECT / "scripts/wbg.ps1",
               PROJECT / "scripts/request_cancel_linux.py"] + sorted((PROJECT / "scripts/windows").glob("*.ps1"))
    sources += sorted(path for path in (PROJECT / "fixtures/stage-b-aes128").rglob("*") if path.is_file())
    container_bootstrap = PROJECT / 'scripts/wbg-container.ps1'
    if container_bootstrap.is_file():
        sources.append(container_bootstrap)
    fingerprints = []
    for source_file in sources:
        relative = source_file.relative_to(PROJECT)
        copied = snapshot / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, copied)
        fingerprints.append({"path": str(relative), "sha256": _hash(copied)})
    atomic_json(run / "orchestrator-lock.json", {"scope": "worker executes frozen source and resources; supervisor/bootstrap sources retained; no automatic resume or clean rebuild claim", "files": fingerprints})
    if os.environ.get("WBG_WINDOWS_HOST_B64"):
        host = json.loads(base64.b64decode(os.environ["WBG_WINDOWS_HOST_B64"], validate=True).decode("utf-8"))
        if host.get("schema_version") != 1 or not host.get("ready"):
            raise ValueError("invalid Windows host provenance")
        atomic_json(run / "windows-host.json", host)
    atomic_json(run / "requested-config.json", requested)
    atomic_json(run / "effective-config.json", effective)
    _atomic_text(run / "requested-config.yaml", to_yaml(requested))
    _atomic_text(run / "effective-config.yaml", to_yaml(effective))
    if os.environ.get("WBG_ORIGINAL_CONFIG"):
        shutil.copyfile(os.environ["WBG_ORIGINAL_CONFIG"], run / "host-requested-config.yaml")
    shutil.copyfile(doctor.BASELINE, run / "source-lock.json")
    atomic_json(run / "environment.json", environment)
    inputs.generate(run / "inputs", effective)
    target = run / "target"
    target.mkdir()
    source = Path(effective["target"]["source"])
    shutil.copyfile(source, target / "source.c")
    if _hash(target / "source.c") != effective["target"]["sha256"]:
        raise ValueError("copied source hash differs from effective config")
    wrapper = WRAPPERS / (effective["target"]["abi"] + ".c")
    shutil.copyfile(wrapper, target / "wrapper.c")
    shutil.copyfile(RESOURCES / "main.c", target / "main.c")
    shutil.copyfile(RESOURCES / "Makefile", target / "Makefile")
    (run / "checks").mkdir()
    (run / "logs").mkdir()
    atomic_json(run / "target-provenance.json", {
        "original_path": str(source), "copied_path": str(target / "source.c"),
        "source_sha256": effective["target"]["sha256"],
        "wrapper_sha256": _hash(target / "wrapper.c"),
        "main_sha256": _hash(target / "main.c"),
        "makefile_sha256": _hash(target / "Makefile"),
    })


def _load_worker(run: Path) -> dict | None:
    path = run / "worker-result.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _terminal(monitoring: dict, worker: dict | None, run: Path) -> dict:
    trigger = monitoring.get("trigger")
    if trigger:
        kind = trigger["kind"]
        if kind in {"initial_disk_gate", "timeout", "output_limit",
                    "work_volume_reserve", "data_volume_reserve", "probe_timeout", "memory_reserve"}:
            status, reason = "resource_limit", kind
        elif kind in {"explicit_cancel_marker", "terminal_sigint", "approval_declined", "approval_timeout"}:
            status, reason = "cancelled", kind
        else:
            status, reason = "error", kind
        stage_path = run / "stage.json"
        stage = json.loads(stage_path.read_text(encoding="utf-8")).get("stage") if stage_path.exists() else "preflight"
        return {"status": status, "reason_code": reason, "completed_stage": stage,
                "execution": {"status": "incomplete"}, "recovery": {"status": "undetermined"},
                "monitor_trigger": trigger}
    if worker is None:
        return {"status": "error", "reason_code": "worker_exit_without_result",
                "completed_stage": "unknown", "execution": {"status": "incomplete"},
                "recovery": {"status": "undetermined"},
                "worker_exit_code": monitoring.get("exit_code")}
    if worker.get("status") not in EXIT or monitoring.get("exit_code") != EXIT[worker["status"]]:
        return {"status": "error", "reason_code": "worker_exit_result_mismatch",
                "completed_stage": worker.get("completed_stage"),
                "execution": {"status": "incomplete"},
                "recovery": worker.get("recovery", {"status": "undetermined"}),
                "worker_exit_code": monitoring.get("exit_code")}
    if worker["status"] == "probe_completed" and json.loads((run / "operation.json").read_text())["command"] != "probe":
        raise ValueError("diagnostic completion cannot substitute analysis verification")
    return worker


def _report(result: dict) -> str:
    from . import delivery
    run = Path(result['locations']['linux_run'])
    return delivery.report(run, result, delivery.recovery(run, result))


def _manifest(run: Path) -> dict:
    files = []
    for path in sorted(run.rglob("*")):
        if path.is_file() and not path.is_symlink() and path != run / "manifest.json":
            files.append({"path": str(path.relative_to(run)).replace("\\", "/"),
                          "bytes": path.stat().st_size, "sha256": _hash(path)})
    return {"scope": "completed Linux run files at manifest creation; excludes only root manifest.json and external export",
            "files": files, "file_count": len(files)}


def _export(run: Path, out: Path) -> None:
    selected = ["requested-config.json", "effective-config.json", "requested-config.yaml",
        "effective-config.yaml", "source-lock.json", "environment.json", "target-provenance.json",
        "budget-group.json", "accounting.json", "windows-host.json", "orchestrator-lock.json",
        "estimate.json", "progress.json", "workflow-state.json", "formal-authorized.json",
        "budget-extensions.json", "boundary-state.json", "operation.json", "probe.json",
        "commands.json", "candidate.json", "cpa.csv", "holdout-ciphertexts.bin", "resource.json",
        "locations.json", "result.json", "report.md", "recovery.json", "validation.json", "manifest.json"]
    public = {"result.json", "report.md", "recovery.json", "validation.json"}
    evidence = out / "evidence"
    evidence.mkdir(exist_ok=True)
    for name in selected:
        source = run / name
        if source.is_file():
            destination = out / name if name in public else evidence / ("run-manifest.json" if name=="manifest.json" else name)
            shutil.copyfile(source, destination)
    for name in ("inputs", "checks", "decisions", "logs"):
        if (run / name).is_dir():
            destination = out / "logs" if name=="logs" else evidence / name
            shutil.copytree(run / name, destination, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("missing-header", "nvalgrind-build"))
    if (run / "target").is_dir():
        target = evidence / "target"
        target.mkdir(exist_ok=True)
        for path in (run / "target").iterdir():
            if path.is_file() and (path.suffix in {".c", ".h"} or path.name=="Makefile"):
                shutil.copyfile(path, target / path.name)
    pilot_csv = run / "pilot-processed/pilot-cpa.csv"
    if pilot_csv.is_file(): shutil.copyfile(pilot_csv, evidence / "pilot-cpa.csv")
    files = [{"path":p.relative_to(out).as_posix(), "bytes":p.stat().st_size,"sha256":_hash(p)}
             for p in sorted(out.rglob("*")) if p.is_file() and p!=out/"manifest.json"]
    atomic_json(out / "manifest.json", {"schema_version":1,"run_id":run.name,
        "scope":"exported review files; full originals remain in owned runtime until explicit cleanup", "files":files})


def _remaining_budget(effective: dict) -> tuple[dict, dict]:
    group = f"{effective['experiment']}:{effective['inputs']['seed']}"
    prior = []
    imported = []
    if os.environ.get('WBG_PRIOR_ACCOUNTING'):
        document = json.loads(Path(os.environ['WBG_PRIOR_ACCOUNTING']).read_text(encoding='utf-8-sig'))
        if document.get('schema_version') != 1 or not isinstance(document.get('records'), list):
            raise ValueError('invalid imported accounting schema')
        seen = set()
        for row in document['records']:
            if row['run_id'] in seen:
                raise ValueError('duplicate imported accounting run')
            seen.add(row['run_id'])
            if row.get('group') != group:
                continue
            if row.get('unfinished'):
                raise RuntimeError('unfinished prior run requires audit before migration')
            if row.get('target_sha256') != effective['target']['sha256']:
                raise ValueError('experiment group target identity conflict')
            if type(row.get('occupied_bytes')) is not int or row['occupied_bytes'] < 0:
                raise ValueError('invalid imported occupied bytes')
            if (type(row.get('elapsed_seconds')) not in (int, float) or
                    not math.isfinite(row['elapsed_seconds']) or row['elapsed_seconds'] < 0):
                raise ValueError('invalid imported elapsed time')
            if (type(row.get('group_max_output_bytes')) is not int or row['group_max_output_bytes'] < 1 or
                    not (row.get('group_max_seconds') is None or
                         type(row['group_max_seconds']) is int and row['group_max_seconds'] > 0)):
                raise ValueError('invalid imported group limits')
            imported.append(row)
    for folder in sorted((WORK / "runs").glob("*-stageB-*")):
        meta = folder / "budget-group.json"
        if not meta.is_file():
            continue
        record = json.loads(meta.read_text(encoding="utf-8"))
        if record.get("group") != group:
            continue
        if any(row['run_id'] == record['run_id'] for row in imported):
            raise ValueError('run appears in both imported and local accounting')
        accounting = folder / "accounting.json"
        if not accounting.is_file():
            raise RuntimeError(f"unfinished prior run requires audit before retry: {folder}")
        prior.append((record, json.loads(accounting.read_text(encoding="utf-8")), folder))
    requested = effective["resources"]
    finite_prior = [row[0]["group_max_seconds"] for row in prior if row[0]["group_max_seconds"] is not None]
    finite_prior += [row['group_max_seconds'] for row in imported if row['group_max_seconds'] is not None]
    maximum_seconds = max(finite_prior) if finite_prior else requested["timeout_seconds"]
    maximum_bytes = (imported[0]['group_max_output_bytes'] if imported else
                     prior[0][0]["group_max_output_bytes"] if prior else requested["output_limit_mib"] * 2**20)
    original_maximum_seconds = maximum_seconds
    grant = authorization(effective)
    if grant:
        maximum_bytes = max(maximum_bytes, grant["max_total_output_bytes"])
        if grant.get("time_policy") == "user_controlled" and requested["timeout_seconds"] is None:
            maximum_seconds = None
        elif grant["max_total_seconds"] is not None:
            maximum_seconds = max(maximum_seconds or 0, grant["max_total_seconds"])
    if requested["timeout_seconds"] is None and (prior or imported) and maximum_seconds is not None:
        raise ValueError("removing an existing group deadline requires explicit scoped authorization")
    for _, _, prior_folder in prior:
        prior_config = prior_folder / "effective-config.json"
        if prior_config.is_file() and json.loads(prior_config.read_text())["target"]["sha256"] != effective["target"]["sha256"]:
            raise ValueError("experiment group target identity conflict")
    if ((requested["timeout_seconds"] is not None and maximum_seconds is not None and
         requested["timeout_seconds"] > maximum_seconds) or requested["output_limit_mib"] * 2**20 > maximum_bytes):
        raise ValueError("retry cannot increase the experiment group's original budget")
    elapsed = sum(item["elapsed_seconds"] for _, item, _ in prior) + sum(row['elapsed_seconds'] for row in imported)
    occupied = sum(max(int(account.get("output_bytes", 0)), sum(path.stat().st_size for path in folder.rglob("*") if path.is_file()))
                   for _, account, folder in prior) + sum(row['occupied_bytes'] for row in imported)
    remaining_seconds = int(maximum_seconds - elapsed) if maximum_seconds is not None else None
    remaining_mib = int((maximum_bytes - occupied) // 2**20)
    if (remaining_seconds is not None and remaining_seconds < 1) or remaining_mib < 1:
        raise RuntimeError("experiment group budget exhausted")
    adjusted = copy.deepcopy(effective)
    adjusted["resources"]["timeout_seconds"] = (min(requested["timeout_seconds"], remaining_seconds)
        if requested["timeout_seconds"] is not None and remaining_seconds is not None else requested["timeout_seconds"])
    adjusted["resources"]["output_limit_mib"] = min(requested["output_limit_mib"], remaining_mib)
    return adjusted, {"group": group, "group_max_seconds": maximum_seconds,
                      "original_group_max_seconds": original_maximum_seconds,
                      "budget_amendment": grant,
                      "time_policy": "user_controlled" if maximum_seconds is None else "explicit_deadline",
                      "group_max_output_bytes": maximum_bytes,
                      "prior_run_ids": [row['run_id'] for row in imported] + [item[0]["run_id"] for item in prior],
                      "prior_elapsed_seconds": elapsed, "prior_output_bytes": occupied,
                      "effective_remaining_seconds": adjusted["resources"]["timeout_seconds"],
                      "effective_remaining_output_mib": adjusted["resources"]["output_limit_mib"]}


def execute(command: str, requested: dict, effective: dict, out: Path | None) -> dict:
    if effective["environment"]["backend"] != BACKEND:
        return response("unsupported", "runtime_backend_mismatch", command=command,
                        execution={"status": "not_started"}, recovery={"status": "not_attempted"},
                        configured=effective["environment"]["backend"], actual=BACKEND)
    environment = doctor.check()
    if not environment["ready"]:
        return response("error", "environment_not_ready", command=command,
                        execution={"status": "not_started"}, recovery={"status": "not_attempted"},
                        failed_checks=[item for item in environment["checks"] if not item["passed"]])
    mounted_export = bool(BACKEND == "docker" and os.environ.get("WBG_EXPORT_MOUNT_ROOT") == "1" and out is not None
                          and out.resolve() == Path("/exports") and out.is_dir() and not any(out.iterdir()))
    if out is not None and out.exists() and not mounted_export:
        return response("error", "output_exists", command=command,
                        execution={"status": "not_started"}, recovery={"status": "not_attempted"},
                        output=str(out))
    lock_path = WORK / ".stage-b.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return response("error", "task_busy", command=command,
                            execution={"status": "not_started"}, recovery={"status": "not_attempted"})
        try:
            effective, group_budget = _remaining_budget(effective)
        except (RuntimeError, ValueError) as exc:
            return response("resource_limit" if "exhausted" in str(exc) else "error",
                            "group_budget_unavailable", command=command,
                            execution={"status": "not_started"}, recovery={"status": "not_attempted"},
                            detail=str(exc))
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-stageB-" + secrets.token_hex(4)
        run = WORK / "runs" / run_id
        review = out.resolve() if out is not None else DEFAULT_EXPORT / run_id
        if review.exists() and not mounted_export:
            return response("error", "output_exists", command=command,
                            execution={"status": "not_started"}, recovery={"status": "not_attempted"},
                            output=str(review))
        run.mkdir(parents=True, exist_ok=False)
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        stat = Path("/proc/self/stat").read_text()
        start_ticks = int(stat[stat.rfind(")") + 2:].split()[19])
        atomic_json(WORK / "active.json", {"run_id": run_id, "pid": os.getpid(),
                                          "launch_token": os.environ.get("WBG_LAUNCH_TOKEN") or secrets.token_hex(32)[:32],
                                          "boot_id": boot_id, "start_ticks": start_ticks})
        result = None
        worker = None
        monitoring = None
        try:
            review.mkdir(parents=True, exist_ok=mounted_export)
            atomic_json(run / "budget-group.json", {"run_id": run_id, **group_budget})
            _prepare(run, requested, effective, environment)
            atomic_json(run / "operation.json", {"command": command, "protocol": "interactive-boundaries-v2"})
            limits = effective["resources"]
            argv = [sys.executable, "-m", "wbg.worker", "--run", str(run)]
            worker_env = os.environ.copy()
            worker_env["PYTHONPATH"] = str(run / "orchestrator/src")
            monitoring = monitor.run(argv, run_root=run, log_dir=run / "logs/worker",
                                     timeout_seconds=limits["timeout_seconds"],
                                     output_limit_mib=limits["output_limit_mib"],
                                     reserve_mib=limits["data_volume_reserve_mib"],
                                     cancel_marker=run / "cancel.request", env=worker_env,
                                     budget_policy=effective["budget"])
            atomic_json(run / "resource.json", monitoring)
            worker = _load_worker(run)
            result = _terminal(monitoring, worker, run)
        except Exception as exc:
            result = {"status": "error", "reason_code": "supervisor_exception",
                      "completed_stage": "supervision", "execution": {"status": "incomplete"},
                      "recovery": worker.get("recovery", {"status": "undetermined"}) if worker else {"status": "undetermined"},
                      "error": repr(exc)}
        locations = {"linux_run": str(run), "review_export": str(review),
                     "windows_review_export": os.environ.get("WBG_WINDOWS_EXPORT_ROOT") or _windows_location(review)}
        progress = run / "progress.json"
        if progress.is_file():
            view = json.loads(progress.read_text())
            view.update(status=result["status"], decision=None, estimated_remaining_seconds=None,
                        recovery=result.get("recovery"), progress={"stage": result.get("completed_stage"),
                                                                 "completed": None, "total": None})
            atomic_json(progress, view)
        result = response(result["status"], result.get("reason_code"),
                          run_id=run_id, command=command, completed_stage=result.get("completed_stage"),
                          stage_semantics="last reached stage; completed only when execution.status=passed",
                          execution=result.get("execution", {"status": "incomplete"}),
                          recovery=result.get("recovery", {"status": "undetermined"}),
                          metrics=result.get("metrics"),
                          io_pairs_checked=result.get("io_pairs_checked"),
                          config={"requested": str(run / "requested-config.yaml"),
                                  "effective": str(run / "effective-config.yaml")},
                          evidence={"cpa_csv": str(run / "cpa.csv") if (run / "cpa.csv").is_file() else None,
                                    "validation": str(run / "validation.json") if (run / "validation.json").is_file() else None},
                          timing={"elapsed_seconds": monitoring.get("elapsed_seconds") if monitoring else None},
                          resource={"record": str(run / "resource.json") if monitoring else None},
                          locations=locations, warnings=[],
                          detail=result.get("error"), monitor_trigger=result.get("monitor_trigger"))
        if monitoring:
            result["timing"].update(waiting_seconds=monitoring.get("waiting_seconds"),
                                    compute_seconds=monitoring.get("compute_seconds"))
        try:
            atomic_json(run / "locations.json", locations)
            result["retention"] = {"decision_required": True, "default": "all", "choices": ["all", "evidence", "minimal"]}
            atomic_json(run / "result.json", result)
            _atomic_text(run / "report.md", _report(result))
            atomic_json(run / "accounting.json", {
                "elapsed_seconds": monitoring.get("elapsed_seconds") if monitoring else 0,
                "output_bytes": sum(path.stat().st_size for path in run.rglob("*") if path.is_file()),
                "measurement": "Linux run logical bytes before manifest; retry admission remeasures all prior files"})
            atomic_json(run / "manifest.json", _manifest(run))
            _export(run, review)
        except Exception as exc:
            result["status"] = "error"
            result["reason_code"] = "delivery_failure"
            result["detail"] = repr(exc)
            atomic_json(run / "result.json", result)
            try:
                _atomic_text(run / "report.md", _report(result))
                atomic_json(run / "manifest.json", _manifest(run))
            except Exception:
                pass
        active = WORK / "active.json"
        try:
            if json.loads(active.read_text(encoding="utf-8")).get("run_id") == run_id:
                active.unlink()
        except (FileNotFoundError, ValueError, OSError):
            pass
        return result
