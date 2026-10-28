"""Exercise the real Linux process-group timeout path with a test-only child."""

from pathlib import Path
import tempfile
import unittest
import sys

from wbg.monitor import _group_members, run


@unittest.skipUnless(sys.platform == "linux", "Linux /proc required")
class StageBMonitorTest(unittest.TestCase):
    def test_timeout_cleans_child_that_ignores_term(self):
        with tempfile.TemporaryDirectory(prefix="wbg-b-monitor-") as folder:
            root = Path(folder)
            child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
            parent = ("import subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)")
            result = run([sys.executable, "-c", parent], run_root=root,
                         log_dir=root / "logs", timeout_seconds=1,
                         output_limit_mib=10, reserve_mib=0)
            self.assertEqual(result["trigger"]["kind"], "timeout", result)
            self.assertGreaterEqual(result["rss_samples"], 1)
            self.assertLess(result["elapsed_seconds"], 5)
            self.assertEqual(_group_members(result["process_group"]), [])


if __name__ == "__main__":
    unittest.main()
