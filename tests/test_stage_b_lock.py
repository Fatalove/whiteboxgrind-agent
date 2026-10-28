"""A second CLI process must refuse to start while the run lock is held."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


from wbg.runtime import WORK_ROOT as WORK


@unittest.skipUnless(sys.platform == "linux", "Linux flock required")
class StageBLockTest(unittest.TestCase):
    def test_second_process_reports_busy_without_creating_run(self):
        lock = WORK / ".stage-b.lock"
        before = {path.name for path in (WORK / "runs").glob("*-stageB-*")}
        with lock.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            process = subprocess.run([sys.executable, "-m", "wbg", "demo", "--json"],
                                     env=os.environ.copy(), capture_output=True, text=True, timeout=30)
            fcntl.flock(stream, fcntl.LOCK_UN)
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 40, process.stderr)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason_code"], "task_busy")
        self.assertEqual(before, {path.name for path in (WORK / "runs").glob("*-stageB-*")})


if __name__ == "__main__":
    unittest.main()
