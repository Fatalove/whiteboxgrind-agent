"""Stable local entry point for the bounded Stage B process supervisor."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import re
import sys

from . import config, doctor, execution
from .protocol import EXIT, response
from . import workflow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wbg")
    commands = parser.add_subparsers(dest="command", required=True)
    ready = commands.add_parser("doctor", help="read-only environment and toolchain check")
    ready.add_argument("--json", action="store_true")
    demo = commands.add_parser("demo", help="run the ordinary AES preset")
    demo.add_argument("--json", action="store_true")
    demo.add_argument("--out", type=Path)
    analyze = commands.add_parser("analyze", help="analyze one configured C target")
    analyze.add_argument("--config", type=Path, required=True)
    analyze.add_argument("--out", type=Path, required=True)
    analyze.add_argument("--json", action="store_true")
    probe = commands.add_parser("probe", help="one complete trace diagnosis, never a recovery result")
    probe.add_argument("--config", type=Path, required=True)
    probe.add_argument("--out", type=Path, required=True)
    probe.add_argument("--json", action="store_true")
    cancel = commands.add_parser("cancel", help="cancel only the identified active run")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--json", action="store_true")
    status = commands.add_parser("status", help="current stage and remaining estimate; no candidate material")
    status.add_argument("--run-id")
    status.add_argument("--json", action="store_true")
    decision = commands.add_parser("decide", help="record a user's choice at the current checkpoint")
    decision.add_argument("--run-id", required=True)
    decision.add_argument("--checkpoint", required=True)
    decision.add_argument("--choice", choices=["continue", "stop"], required=True)
    decision.add_argument("--additional-seconds", type=int, default=0,
                          help="explicitly approved added time; does not change disk limits")
    decision.add_argument("--approval-quote", help="required human approval text for added time")
    decision.add_argument("--json", action="store_true")
    history = commands.add_parser("history", help="query up to five comparable local analysis records")
    history_commands = history.add_subparsers(dest="history_command", required=True)
    query = history_commands.add_parser("query")
    query.add_argument("--config", type=Path, required=True)
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--json", action="store_true")
    cases = commands.add_parser("case", help="prepare a portable input/output task")
    case_commands = cases.add_subparsers(dest="case_command", required=True)
    prepare = case_commands.add_parser("prepare")
    prepare.add_argument("--case-root", type=Path, required=True)
    prepare.add_argument("--source")
    prepare.add_argument("--example", action="store_true")
    prepare.add_argument("--seed", type=int)
    prepare.add_argument("--trace-count", type=int)
    prepare.add_argument("--json", action="store_true")
    cleanup = commands.add_parser("cleanup", help="plan or apply a human-selected terminal data policy")
    cleanup_commands = cleanup.add_subparsers(dest="cleanup_command", required=True)
    for verb in ("plan", "apply"):
        entry = cleanup_commands.add_parser(verb)
        entry.add_argument("--run-id", required=True)
        entry.add_argument("--export-root", type=Path)
        entry.add_argument("--json", action="store_true")
        if verb == "apply":
            entry.add_argument("--plan-id", required=True)
            entry.add_argument("--keep", choices=("all", "evidence", "minimal"), required=True)
            entry.add_argument("--approval-quote", required=True)
    return parser


def _run_path(run_id: str | None, *, require_active: bool = False) -> Path:
    active = workflow.read(execution.WORK, "active.json", {})
    run_id = run_id or active.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}T\d{6}Z-stageB-[0-9a-f]{8}", run_id):
        raise ValueError("no active run or invalid run ID")
    run = execution.WORK / "runs" / run_id
    if not run.is_dir():
        raise ValueError("unknown run ID")
    if require_active:
        if active.get("run_id") != run_id:
            raise ValueError("run is not active")
        stat = Path(f"/proc/{int(active['pid'])}/stat").read_text()
        ticks = int(stat[stat.rfind(")") + 2:].split()[19])
        if (ticks != active.get("start_ticks") or
                Path("/proc/sys/kernel/random/boot_id").read_text().strip() != active.get("boot_id")):
            raise ValueError("stale active run identity")
    return run


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "case":
            from .cases import prepare
            result = prepare(args.case_root, args.source, example=args.example, seed=args.seed, trace_count=args.trace_count)
            code = 0 if result['status'] == 'prepared' else 2
        elif args.command == "cleanup":
            from . import retention
            run = _run_path(args.run_id)
            result = (retention.plan(run, execution.WORK, args.export_root) if args.cleanup_command == 'plan' else
                retention.apply(run, execution.WORK, args.plan_id, args.keep, args.approval_quote, args.export_root))
            code = 0
        elif args.command == "doctor":
            result = doctor.check()
            code = 0 if result["ready"] else 2
        elif args.command == "history":
            from .history_query import query
            _, effective = config.load(args.config)
            result = query(effective, args.limit)
            code = 0
        elif args.command == "status":
            if args.run_id is None and not (execution.WORK / "active.json").exists():
                print(json.dumps({"schema_version": 1, "status": "idle", "run_id": None,
                                  "progress": None, "estimated_remaining_seconds": None, "decision": None}))
                return 0
            run = _run_path(args.run_id)
            terminal = workflow.read(run, "result.json")
            if terminal:
                result = {"schema_version": 1, "run_id": run.name, "status": terminal["status"],
                          "progress": {"stage": terminal.get("completed_stage")},
                          "recovery": {key: value for key, value in (terminal.get("recovery") or {}).items()
                                       if key in {"status", "holdout_passed", "holdout_total", "reason_code"}}, "estimated_remaining_seconds": None,
                          "decision": None, "retention": {"decision_required": workflow.read(run, "retention.json", {}).get("status") != "completed",
                              "default": "all", "choices": ["all", "evidence", "minimal"]}}
            else:
                _run_path(run.name, require_active=True)
                result = workflow.read(run, "progress.json") or {
                    "schema_version": 1, "run_id": run.name, "status": "running",
                    "progress": workflow.read(run, "stage.json", {"stage": "preflight"}),
                    "estimated_remaining_seconds": None, "decision": None}
                sampled = workflow.read(run, "resource-progress.json", {})
                result["observations"] = {"logical_output_bytes": execution.monitor._tree_size(run),
                    "sampled_rss_sum_max_bytes": sampled.get("rss_sum_sampled_max_bytes")}
            code = 0
        elif args.command == "decide":
            result = workflow.decide(_run_path(args.run_id, require_active=True), args.checkpoint, args.choice,
                                     args.additional_seconds, args.approval_quote)
            code = 0
        elif args.command == "cancel":
            run = _run_path(args.run_id, require_active=True)
            active = workflow.read(execution.WORK, "active.json")
            sys.path.insert(0, str(config.PROJECT / "scripts"))
            from request_cancel_linux import request
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                accepted = request(active["launch_token"], execution.WORK, source="agent_cancel", expected_run_id=run.name)
            result = {"schema_version": 1, "status": "accepted" if accepted == 0 else "error", **json.loads(output.getvalue())}
            code = 0 if accepted == 0 else 40
        elif args.command == "demo":
            requested, effective = config.demo()
            result = execution.execute("demo", requested, effective, args.out)
            code = EXIT[result["status"]]
        else:
            requested, effective = config.load(args.config)
            result = execution.execute(args.command, requested, effective, args.out)
            code = EXIT[result["status"]]
    except config.UnsupportedConfig as exc:
        result = response("unsupported", exc.reason_code, command=args.command, detail=str(exc),
                          evidence=exc.evidence, execution={"status": "not_started"},
                          recovery={"status": "not_attempted"})
        code = EXIT["unsupported"]
    except Exception as exc:
        result = response("error", "cli_exception", command=args.command, error=repr(exc),
                          execution={"status": "not_started"}, recovery={"status": "not_attempted"})
        code = EXIT["error"]
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return code
