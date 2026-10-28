"""Bounded test-only faults, using tiny temporary directories and real signals."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wbg import execution, monitor
from wbg.config import demo
from wbg.history import rebuild, summarize


class FaultTests(unittest.TestCase):
    def test_sigint_sigterm_and_explicit_marker_are_distinct_and_cleaned(self):
        for mode in (signal.SIGINT, signal.SIGTERM, "marker"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); marker = root / "cancel"
                def trigger():
                    if mode == "marker": marker.write_text("test-only explicit cancellation")
                    else: os.kill(os.getpid(), mode)
                timer = threading.Timer(0.2, trigger); timer.start()
                try:
                    record = monitor.run([sys.executable, "-c", "import time; time.sleep(15)"],
                                         run_root=root, log_dir=root / "logs", timeout_seconds=5,
                                         output_limit_mib=10, reserve_mib=0, cancel_marker=marker)
                finally: timer.cancel(); timer.join()
                expected = {signal.SIGINT: "terminal_sigint", signal.SIGTERM: "external_signal",
                            "marker": "explicit_cancel_marker"}[mode]
                self.assertEqual(record["trigger"]["kind"], expected)
                result = execution._terminal(record, None, root)
                self.assertEqual(result["status"], "error" if mode == signal.SIGTERM else "cancelled")
                self.assertEqual(monitor._group_members(record["process_group"]), [])

    def test_tiny_disk_threshold_before_and_during_worker(self):
        for initial in (True, False):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if initial: (root / "test-only-data").write_bytes(bytes(2 * 2**20))
                code = "from pathlib import Path; import time; Path('test-only-data').write_bytes(bytes(2*2**20)); time.sleep(15)"
                record = monitor.run([sys.executable, "-c", code], run_root=root,
                                     log_dir=root / "logs", timeout_seconds=8, output_limit_mib=1,
                                     reserve_mib=0, env=dict(os.environ, PWD=str(root))) if initial else None
                if not initial:
                    code = f"from pathlib import Path; import time; Path({str(root / 'test-only-data')!r}).write_bytes(bytes(2*2**20)); time.sleep(15)"
                    record = monitor.run([sys.executable, "-c", code], run_root=root,
                                         log_dir=root / "logs", timeout_seconds=8,
                                         output_limit_mib=1, reserve_mib=0)
                self.assertEqual(record["trigger"]["kind"], "initial_disk_gate" if initial else "output_limit")
                self.assertEqual(execution._terminal(record, None, root)["status"], "resource_limit")
                if record["process_group"]: self.assertFalse(monitor._group_members(record["process_group"]))

    def test_unknown_sigkill_and_worker_exception_do_not_imply_oom(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, code in [("kill", "import os,signal; os.kill(os.getpid(), signal.SIGKILL)"),
                               ("crash", "raise RuntimeError('test-only crash')")]:
                record = monitor.run([sys.executable, "-c", code], run_root=root,
                                     log_dir=root / name, timeout_seconds=5,
                                     output_limit_mib=10, reserve_mib=0)
                result = execution._terminal(record, None, root)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["reason_code"], "worker_exit_without_result")
                self.assertNotIn("oom", json.dumps(result).lower())

    def test_delivery_failure_retains_completed_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); work = root / "test-only-work"; work.mkdir(); (work / "runs").mkdir()
            requested, config = demo()
            record = {"trigger": None, "exit_code": 0, "elapsed_seconds": 0.01}
            verified = {"status": "verified", "reason_code": None, "completed_stage": "independent_holdout",
                        "execution": {"status": "passed"}, "recovery": {"status": "verified", "holdout_passed": 16, "holdout_total": 16}}
            with patch.object(execution, "WORK", work), patch.object(execution.doctor, "check", return_value={"ready": True}), \
                 patch.object(execution.monitor, "run", return_value=record), \
                 patch.object(execution, "_load_worker", return_value=verified), \
                 patch.object(execution, "_export", side_effect=OSError("test-only export fault")):
                result = execution.execute("demo", requested, config, root / "review")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["reason_code"], "delivery_failure")
            self.assertEqual(result["recovery"]["status"], "verified")
            run = Path(result["locations"]["linux_run"])
            self.assertIn("delivery_failure", (run / "report.md").read_text())

    def test_hard_stopped_supervisor_is_unfinished_and_index_rebuild_is_key_free(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); runs = root / "runs"; runs.mkdir(); run = runs / "test-only-stageB-unfinished"; run.mkdir()
            marker = root / "active.json"
            code = ("import json,os,time; from pathlib import Path; "
                    "s=Path('/proc/self/stat').read_text(); "
                    f"Path({str(marker)!r}).write_text(json.dumps({{'run_id': {run.name!r}, 'pid': os.getpid(), "
                    "'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), "
                    "'start_ticks': int(s[s.rfind(')')+2:].split()[19])})); "
                    "from wbg.monitor import run; "
                    f"r=run([{sys.executable!r},'-c','import time; time.sleep(15)'],run_root=Path({str(run)!r}),"
                    f"log_dir=Path({str(run / 'logs')!r}),timeout_seconds=10,output_limit_mib=10,reserve_mib=0); "
                    f"Path({str(run / 'result.json')!r}).write_text(json.dumps(r))")
            process = subprocess.Popen([sys.executable, "-c", code])
            try:
                for _ in range(100):
                    if (run / "resource-progress.json").exists(): break
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                active = json.loads(marker.read_text())
                pgid = json.loads((run / "resource-progress.json").read_text())["process_group"]
                self.assertEqual(summarize(run, active)["reason_code"], "active")
                process.kill(); process.wait(timeout=3)
                os.killpg(pgid, signal.SIGTERM)
                for _ in range(50):
                    if not monitor._group_members(pgid): break
                    time.sleep(0.02)
                self.assertFalse(monitor._group_members(pgid))
                self.assertFalse((run / "result.json").exists())
                self.assertEqual(summarize(run, active)["reason_code"], "unfinished")
                finished = runs / "test-only-stageB-finished"; finished.mkdir()
                (finished / "result.json").write_text(json.dumps({"status": "verified", "key_hex": "SECRET_TEST_ONLY", "recovery": {"status": "verified"}}))
                output = root / "index.jsonl"
                rebuild(runs, output, marker); before = output.read_bytes()
                rebuild(runs, output, marker)
                self.assertEqual(before, output.read_bytes())
                self.assertNotIn(b"SECRET_TEST_ONLY", before)
                self.assertNotIn(b"key_hex", before)
            finally:
                if process.poll() is None: process.kill(); process.wait()


if __name__ == "__main__": unittest.main()
