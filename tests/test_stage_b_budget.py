"""Budget decisions/estimates are tested separately from recovery evidence."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wbg import monitor, workflow, execution
from wbg.config import demo, normalize, PROJECT, ConfigError
from wbg.inputs import generate
from wbg.checks import input_integrity
from wbg.protocol import atomic_json


def fixture_quote():
    return workflow.quote([{"name": "pilot-" + name, "elapsed_seconds": value}
                           for name, value in zip(("collect", "filter", "unique", "leakage", "cpa"),
                                                  (5, 20, 6, 4, 23))], 10, 100, 1024, 4096, 10 * 2**20)


class BudgetTests(unittest.TestCase):
    def test_status_without_active_run_is_idle_not_an_analysis_failure(self):
        from wbg.cli import main
        with tempfile.TemporaryDirectory() as folder, patch.object(execution, "WORK", Path(folder)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = main(["status", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "idle")

    def test_auto_pilot_sizes_and_full_formal_input_integrity(self):
        raw, _ = demo()
        for count, pilot in ((10, 10), (100, 10), (500, 50)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as folder:
                raw["inputs"]["trace_count"] = count
                effective = normalize(raw, PROJECT)
                self.assertEqual(effective["inputs"]["pilot_count"], pilot)
                manifest = generate(Path(folder) / "inputs", effective)
                self.assertEqual(manifest["files"]["analysis.bin"]["blocks"], count)
                self.assertEqual(manifest["files"]["pilot.bin"]["blocks"], pilot)
                self.assertTrue(input_integrity(Path(folder) / "inputs")["passed"])
        bad = copy.deepcopy(raw); bad["inputs"]["pilot_count"] = 501
        with self.assertRaises(ConfigError): normalize(bad, PROJECT)

    def test_quote_is_remaining_only_and_does_not_claim_recovery_or_a_bound(self):
        quote = fixture_quote()
        self.assertGreater(quote["remaining_seconds"]["high"], quote["remaining_seconds"]["low"])
        self.assertFalse(quote["recovery_guaranteed"])
        self.assertNotIn("elapsed_seconds", quote)
        self.assertNotIn("pilot_all_stages_seconds", quote)
        self.assertIn("not a confidence interval", quote["uncertainty"])
        self.assertEqual([r["stage"] for r in quote["stages"]][:5], list(workflow.STAGES))

    def test_approval_is_required_and_first_answer_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); now = time.monotonic(); state = {}
            atomic_json(root / "estimate.json", fixture_quote())
            workflow.tick(root, state, workflow.DEFAULTS, now, now + 1000)
            self.assertFalse((root / "formal-authorized.json").exists())
            view = workflow.read(root, "progress.json")
            token = view["decision"]["checkpoint_id"]
            with self.assertRaises(ValueError): workflow.decide(root, "0" * 32, "continue")
            workflow.decide(root, token, "continue")
            with self.assertRaises(FileExistsError): workflow.decide(root, token, "stop")
            workflow.tick(root, state, workflow.DEFAULTS, now + 1, now + 1000)
            self.assertTrue((root / "formal-authorized.json").exists())
            self.assertEqual(workflow.read(root, "progress.json")["status"], "running")
            with self.assertRaises(ValueError): workflow.decide(root, token, "continue")

    def test_started_trace_is_not_reported_as_completed_and_overrun_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); now = time.monotonic()
            atomic_json(root / "stage.json", {"stage": "raw-collect", "at_monotonic": now - 10})
            (root / "logs/raw-collect").mkdir(parents=True)
            (root / "logs/raw-collect/stdout.log").write_text("1: " + "00" * 16 + "\n2: " + "11" * 16 + "\n")
            _, progress = workflow.remaining(root, fixture_quote(), now)
            self.assertEqual(progress["completed"], 1)
            atomic_json(root / "stage.json", {"stage": "formal-cpa", "at_monotonic": now - 1000})
            left, progress = workflow.remaining(root, fixture_quote(), now)
            self.assertIsNone(left)
            self.assertIsNone(progress["completed"])
            atomic_json(root / "commands.json", {"commands": [{"name": "raw-collect"}]})
            atomic_json(root / "stage.json", {"stage": "formal-reads", "at_monotonic": now - 1000})
            left, _ = workflow.remaining(root, fixture_quote(), now)
            self.assertIsNotNone(left)  # filtering has not even started

    def test_monitor_stop_no_reply_and_overrun_cleanup_real_processes(self):
        for mode in ("stop", "no_reply", "overrun"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                estimate = fixture_quote()
                if mode == "overrun":
                    estimate["remaining_seconds"] = {"low": 0, "high": 1}
                atomic_json(root / "estimate.json", estimate)
                failures = []
                def answer():
                    try:
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            view = workflow.read(root, "progress.json", {})
                            pending = view.get("decision")
                            if pending:
                                workflow.decide(root, pending["checkpoint_id"], "continue" if mode == "overrun" else "stop")
                                return
                            time.sleep(0.01)
                        raise AssertionError("checkpoint not created")
                    except Exception as exc: failures.append(repr(exc))
                thread = threading.Thread(target=answer) if mode != "no_reply" else None
                if thread: thread.start()
                try:
                    record = monitor.run([sys.executable, "-c", "import time; time.sleep(20)"],
                                         run_root=root, log_dir=root / "logs", timeout_seconds=10,
                                         output_limit_mib=10, reserve_mib=0,
                                         budget_policy={"probe_timeout_seconds": 5, "decision_wait_seconds": 2,
                                                        "overrun_grace_seconds": 1})
                finally:
                    if thread: thread.join(timeout=10)
                self.assertFalse(failures)
                self.assertEqual(record["trigger"]["kind"], "approval_declined" if mode == "stop" else "approval_timeout")
                self.assertFalse(monitor._group_members(record["process_group"]))
                self.assertEqual(execution._terminal(record, None, root)["status"], "cancelled")
                if mode != "overrun": self.assertFalse((root / "formal-authorized.json").exists())

    def test_hard_deadline_and_probe_timeout_remain_resource_limits(self):
        for quote_present, expected in ((False, "probe_timeout"), (True, "timeout")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if quote_present: atomic_json(root / "estimate.json", fixture_quote())
                record = monitor.run([sys.executable, "-c", "import time; time.sleep(10)"],
                                     run_root=root, log_dir=root / "logs", timeout_seconds=2,
                                     output_limit_mib=10, reserve_mib=0,
                                     budget_policy={"probe_timeout_seconds": 1, "decision_wait_seconds": 5,
                                                    "overrun_grace_seconds": 1})
                self.assertEqual(record["trigger"]["kind"], expected)
                self.assertEqual(execution._terminal(record, None, root)["status"], "resource_limit")
                self.assertFalse(monitor._group_members(record["process_group"]))

    def test_explicit_extension_is_recorded_and_changes_only_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            atomic_json(root / "estimate.json", fixture_quote())
            atomic_json(root / "budget-group.json", {"group_max_seconds": 2, "group_max_output_bytes": 12345,
                                                      "prior_elapsed_seconds": 7})
            failures = []
            def answer():
                try:
                    until = time.monotonic() + 5
                    while time.monotonic() < until:
                        pending = (workflow.read(root, "progress.json", {}).get("decision") or {})
                        if pending:
                            token = pending["checkpoint_id"]
                            with self.assertRaises(ValueError): workflow.decide(root, token, "continue", 3)
                            workflow.decide(root, token, "continue", 3, "TEST ONLY: approve three more seconds")
                            return
                        time.sleep(0.01)
                    raise AssertionError("no checkpoint")
                except Exception as exc: failures.append(repr(exc))
            thread = threading.Thread(target=answer); thread.start()
            try:
                record = monitor.run([sys.executable, "-c", "import time; time.sleep(3.2)"],
                                     run_root=root, log_dir=root / "logs", timeout_seconds=2,
                                     output_limit_mib=10, reserve_mib=0,
                                     budget_policy={"probe_timeout_seconds": 1, "decision_wait_seconds": 5,
                                                    "overrun_grace_seconds": 1})
            finally: thread.join(timeout=6)
            self.assertFalse(failures)
            self.assertIsNone(record["trigger"])
            self.assertEqual(record["exit_code"], 0)
            self.assertGreater(record["elapsed_seconds"], 2)
            self.assertEqual(record["explicit_additional_seconds"], 3)
            group = workflow.read(root, "budget-group.json")
            self.assertEqual(group["group_max_seconds"], 5)
            self.assertEqual(group["group_max_output_bytes"], 12345)
            self.assertEqual(group["prior_elapsed_seconds"], 7)
            self.assertEqual(len(workflow.read(root, "budget-extensions.json")["extensions"]), 1)


if __name__ == "__main__": unittest.main()
