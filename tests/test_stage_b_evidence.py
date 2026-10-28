"""Test-only corruption and synthetic numeric fixtures; never recovery evidence."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import y5

from wbg.checks import csv_integrity, input_integrity, absolute_correlation
from wbg.config import demo, normalize, UnsupportedConfig
from wbg.inputs import generate
from wbg.worker import Worker, ENTRY, PipelineError, extract


class EvidenceTests(unittest.TestCase):
    def test_constant_observation_and_prediction_are_explicit(self):
        a = absolute_correlation([3, 3, 3], [1, 2, 3])
        b = absolute_correlation([1, 2, 3], [3, 3, 3])
        self.assertTrue(a["observed_zero_variance"])
        self.assertFalse(a["predicted_zero_variance"])
        self.assertTrue(b["predicted_zero_variance"])
        self.assertEqual(a["absolute_correlation"], 0)
        self.assertAlmostEqual(absolute_correlation([1, 2, 3], [3, 2, 1])["absolute_correlation"], 1)
        with self.assertRaises(ValueError): absolute_correlation([1, float("nan")], [1, 2])

    def test_input_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, config = demo()
            generate(root / "inputs", config)
            self.assertTrue(input_integrity(root / "inputs")["passed"])
            path = root / "inputs/analysis.bin"
            data = bytearray(path.read_bytes()); data[0] ^= 1; path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "input_hash_mismatch"):
                input_integrity(root / "inputs")

    def test_csv_corruption_and_tie_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.csv"
            header = ["key_byte", "guess", "best_correlation", "best_sample"]
            rows = [[byte, guess, "0", 0] for byte in range(16) for guess in range(256)]
            def write(data):
                with path.open("w", newline="") as stream:
                    writer = csv.writer(stream); writer.writerow(header); writer.writerows(data)
            write(rows)
            self.assertTrue(csv_integrity(path, 1)["passed"])
            candidate = extract(path, 1)
            self.assertEqual(candidate["key_hex"], "00" * 16)
            self.assertTrue(all(len(item["tied_guesses"]) == 256 for item in candidate["bytes"]))
            variants = [rows[:-1], rows + [rows[0]]]
            for column, value in [(0, 16), (1, 256), (2, "NaN"), (2, "Inf"), (3, 1)]:
                bad = [row[:] for row in rows]; bad[0][column] = value; variants.append(bad)
            for bad in variants:
                write(bad)
                with self.assertRaises(ValueError): csv_integrity(path, 1)
                with self.assertRaises(ValueError): extract(path, 1)

    def test_chunked_structure_padding_and_34byte_overflow(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "checks").mkdir()
            _, config = demo()
            (root / "effective-config.json").write_text(json.dumps(config))
            worker = Worker(root)
            def trace(name, arrays):
                path = root / name
                writer = y5.writer(str(path), 64)
                for data in arrays:
                    writer.append(data); writer.end_row()
                del writer
                return path
            first = np.zeros(4097, dtype=ENTRY)
            first["width"] = 1; first["pc"] = 123; first["value"][:, 0] = 3
            same = first.copy(); same["addr"] = 999; same["value"][:, 0] = 7
            good = trace("aligned.y5", [first, same])
            self.assertTrue(worker.inspect_reads(good, 2, "aligned")["pc_width_mode_sequences_aligned"])
            bad = same.copy(); bad["pc"][4096] = 124
            with self.assertRaisesRegex(PipelineError, "event.*4096"):
                worker.inspect_reads(trace("different.y5", [first, bad]), 2, "different")
            padded = first[:1].copy(); padded["value"][0, 1] = 1
            with self.assertRaises(PipelineError) as context:
                worker.inspect_reads(trace("padding.y5", [padded]), 1, "padding")
            self.assertEqual(context.exception.reason_code, "nonzero_read_padding")
            wide = first[:1].copy(); wide["width"] = 34; wide["value"] = 255
            self.assertEqual(int(np.unpackbits(wide["value"]).sum()), 272)
            with self.assertRaises(PipelineError) as context:
                worker.inspect_reads(trace("wide.y5", [wide]), 1, "wide")
            self.assertEqual(context.exception.reason_code, "hamming_weight_overflow")
            with self.assertRaises(PipelineError) as context:
                worker.inspect_reads(trace("empty.y5", [first[:0]]), 1, "empty")
            self.assertEqual(context.exception.reason_code, "empty_raw_trace")

    def test_corrupt_y5_rejected(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "checks").mkdir()
            _, config = demo(); (root / "effective-config.json").write_text(json.dumps(config))
            for name, content in [("empty", b""), ("header", b"not a y5"), ("truncated", b"Y5" + bytes(50))]:
                path = root / name; path.write_bytes(content)
                code = ("import resource; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); "
                        "from pathlib import Path; from wbg.worker import Worker; "
                        f"Worker(Path({str(root)!r})).inspect_reads(Path({str(path)!r}),1,{name!r})")
                process = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=5)
                self.assertNotEqual(process.returncode, 0, name)

    def test_actual_elf_header_is_unsupported_before_execution(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / "target"
            header = bytearray(64); header[:6] = b"\x7fELF\x02\x01"; header[18:20] = (62).to_bytes(2, "little")
            path.write_bytes(header)
            raw, _ = demo(); raw["target"]["source"] = str(path)
            raw["target"]["sha256"] = hashlib.sha256(header).hexdigest()
            with self.assertRaises(UnsupportedConfig) as context: normalize(raw, root)
            self.assertEqual(context.exception.reason_code, "input_format_elf")
            self.assertFalse(context.exception.evidence["target_process_started"])


if __name__ == "__main__": unittest.main()
