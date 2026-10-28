"""Continuation fixes: synthetic fixtures and metadata only, never recovery proof."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from wbg.config import demo, PROJECT, load, normalize, ConfigError
from wbg.execution import _manifest, _prepare, _remaining_budget
from wbg import execution
from wbg.budgets import authorization
from wbg.history import summarize
from wbg.worker import Worker

sys.path.insert(0, str(PROJECT / "scripts"))
from request_cancel_linux import request


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        from support import configure
        configure(self)

    def test_budget_amendment_is_scoped_and_preserves_prior_consumption(self):
        requested, _ = load(self.test_config)
        requested["resources"]["timeout_seconds"] = 7200
        effective = normalize(requested, self.test_config.parent)
        self.assertEqual(authorization(effective)["max_total_seconds"], 7200)
        other = json.loads(json.dumps(requested))
        other["inputs"]["seed"] = 20261024
        with self.assertRaises(ConfigError):
            normalize(other, self.test_config.parent)
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            prior = work / "runs/20261025T000000Z-stageB-aaaaaaaa"
            prior.mkdir(parents=True)
            (prior / "budget-group.json").write_text(json.dumps({
                "run_id": prior.name, "group": "synthetic-budget-case:20261023",
                "group_max_seconds": 1800, "group_max_output_bytes": 5120 * 2**20}))
            (prior / "accounting.json").write_text(json.dumps({"elapsed_seconds": 137.299}))
            (prior / "effective-config.json").write_text(json.dumps(effective))
            (prior / "test-only-occupied.bin").write_bytes(bytes(2**20))
            with patch.object(execution, "WORK", work):
                adjusted, group = _remaining_budget(effective)
            self.assertEqual(group["original_group_max_seconds"], 1800)
            self.assertEqual(group["group_max_seconds"], 7200)
            self.assertEqual(group["prior_elapsed_seconds"], 137.299)
            self.assertEqual(adjusted["resources"]["timeout_seconds"], 7062)
            self.assertGreater(group["prior_output_bytes"], 2**20)
            self.assertLess(adjusted["resources"]["output_limit_mib"], 5120)
            self.assertEqual(group["budget_amendment"]["approved_by"], "user")

    def test_cancellation_requires_this_launch_token(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            run_id = "20261026T000000Z-stageB-aaaaaaaa"
            run = work / "runs" / run_id
            run.mkdir(parents=True)
            stat = Path("/proc/self/stat").read_text()
            marker = {"run_id": run_id, "pid": os.getpid(), "launch_token": "a" * 32,
                      "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                      "start_ticks": int(stat[stat.rfind(")") + 2:].split()[19])}
            (work / "active.json").write_text(json.dumps(marker))
            self.assertEqual(request("b" * 32, work), 2)
            self.assertFalse((run / "cancel.request").exists())
            self.assertEqual(request("a" * 32, work), 0)
            self.assertEqual(json.loads((run / "cancel.request").read_text())["launch_token"], "a" * 32)

    def test_root_manifest_only_is_excluded_and_sources_are_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            requested, effective = demo()
            _prepare(root, requested, effective, {"test_only": True})
            (root / "manifest.json").write_text("{}")
            inventory = _manifest(root)
            names = [row["path"] for row in inventory["files"]]
            self.assertIn("inputs/manifest.json", names)
            self.assertNotIn("manifest.json", names)
            lock = json.loads((root / "orchestrator-lock.json").read_text())
            self.assertGreater(len(lock["files"]), 10)
            for record in lock["files"]:
                saved = root / "orchestrator" / record["path"]
                self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), record["sha256"])

    def test_cache_warning_survives_general_warning_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, config = demo()
            (root / "effective-config.json").write_text(json.dumps(config))
            (root / "logs/a").mkdir(parents=True)
            (root / "logs/z").mkdir()
            (root / "logs/a/stderr.log").write_text("WARNING dwarf compatibility\n" * 100)
            (root / "logs/z/stderr.log").write_text("WARNING: Some cache entries were discarded.\n")
            warning = Worker(root).tool_warnings()
            self.assertTrue(warning["general_list_truncated"])
            self.assertEqual(len(warning["observed_log_lines"]), 80)
            self.assertEqual(len(warning["cache_warning_lines"]), 1)
            self.assertIn("discarded", warning["cache_warning_lines"][0]["line"])

    def test_missing_legacy_lock_stays_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "result.json").write_text(json.dumps({"status": "error"}))
            self.assertIsNone(summarize(root)["environment_lock"])
