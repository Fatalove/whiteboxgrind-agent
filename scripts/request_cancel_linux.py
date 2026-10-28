"""Mark only the verified active Stage B run for explicit Windows cancellation."""

import datetime as dt
import argparse
import json
from pathlib import Path
import re


WORK = Path("/home/wbg/whiteboxgrind-work")


def request(token: str, work: Path = WORK, *, source: str = "windows_ctrl_c", expected_run_id: str | None = None) -> int:
    active_path = work / "active.json"
    if not active_path.is_file():
        print(json.dumps({"cancel_requested": False, "reason": "no_active_run"}))
        return 2
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if expected_run_id is not None and active.get("run_id") != expected_run_id:
        print(json.dumps({"cancel_requested": False, "reason": "run_identity_mismatch"}))
        return 2
    if not re.fullmatch(r"[0-9a-f]{32}", token) or active.get("launch_token") != token:
        print(json.dumps({"cancel_requested": False, "reason": "launch_token_mismatch"}))
        return 2
    run_id = active.get("run_id")
    pid = active.get("pid")
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}T\d{6}Z-stageB-[0-9a-f]{8}", run_id):
        return 2
    if type(pid) is not int or pid <= 0:
        return 2
    run = work / "runs" / run_id
    if not run.is_dir() or run.resolve().parent != (work / "runs").resolve():
        return 2
    if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != active.get("boot_id"):
        return 2
    stat_path = Path("/proc") / str(pid) / "stat"
    if not stat_path.is_file():
        return 2
    stat = stat_path.read_text()
    start_ticks = int(stat[stat.rfind(")") + 2:].split()[19])
    if start_ticks != active.get("start_ticks"):
        return 2
    marker = run / "cancel.request"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"source": source, "launch_token": token, "requested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "run_id": run_id}, stream)
            stream.write("\n")
    except FileExistsError:
        pass
    print(json.dumps({"cancel_requested": True, "run_id": run_id}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    return request(args.token)


if __name__ == "__main__":
    raise SystemExit(main())
