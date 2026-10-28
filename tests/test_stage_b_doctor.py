"""Doctor must classify a concrete environment identity mismatch as not ready."""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wbg import cli, doctor


class StageBDoctorTest(unittest.TestCase):
    def test_patch_identity_mismatch_is_not_ready_exit_two(self):
        baseline = json.loads(doctor.BASELINE.read_text(encoding="utf-8"))
        altered = copy.deepcopy(baseline)
        altered["patch_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "baseline.json"
            path.write_text(json.dumps(altered), encoding="utf-8")
            with patch.object(doctor, "BASELINE", path):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = cli.main(["doctor", "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["status"], "not_ready")
        failed = [item["name"] for item in result["checks"] if not item["passed"]]
        self.assertIn("patch_file_sha256", failed)


if __name__ == "__main__":
    unittest.main()
