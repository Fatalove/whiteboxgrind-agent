"""Host disk telemetry loss must stop the owned child, never bypass the reserve."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from wbg.monitor import run, _group_members


@unittest.skipUnless(sys.platform == "linux", "Linux process groups required")
class ContainerMonitorTest(unittest.TestCase):
    def invoke(self, root):
        return run([sys.executable, "-c", "import time; time.sleep(60)"],
                   run_root=root, log_dir=root / "logs", timeout_seconds=None,
                   output_limit_mib=10, reserve_mib=0)

    def test_initial_missing_host_mapping_does_not_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("wbg.monitor.data_free_bytes", side_effect=ValueError("stale telemetry")):
                result = self.invoke(Path(directory))
            self.assertEqual(result["trigger"]["kind"], "host_resource_unavailable")
            self.assertIsNone(result["process_group"])
            self.assertIsNone(result["exit_code"])

    def test_mapping_loss_terminates_live_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("wbg.monitor.data_free_bytes", side_effect=[40 * 2**30, ValueError("stale telemetry")]):
                result = self.invoke(Path(directory))
            self.assertEqual(result["trigger"]["kind"], "host_resource_unavailable")
            self.assertIsNotNone(result["process_group"])
            self.assertEqual(_group_members(result["process_group"]), [])
            self.assertLess(result["elapsed_seconds"], 5)
