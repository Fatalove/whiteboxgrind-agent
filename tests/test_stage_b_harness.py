"""Compile the real Stage B harness against the unchanged ordinary AES fixture."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from Crypto.Cipher import AES


PROJECT = Path(__file__).resolve().parents[1]
from wbg.runtime import ENGINE_ROOT as WORK


class StageBHarnessTest(unittest.TestCase):
    def test_unsigned_abi_and_strict_block_io(self):
        target = PROJECT / "fixtures/ordinary-aes128/adapter.c"
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        resources = PROJECT / "fixtures/stage-b-aes128/resources"
        wrapper = PROJECT / "fixtures/stage-b-aes128/wrappers/unsigned-char-pointer.c"
        with tempfile.TemporaryDirectory(prefix="wbg-b-harness-") as folder:
            root = Path(folder)
            for source, name in [(resources / "main.c", "main.c"),
                                 (resources / "Makefile", "Makefile"),
                                 (wrapper, "wrapper.c"), (target, "source.c")]:
                shutil.copyfile(source, root / name)
            env = dict(os.environ, WBG_ORIGINAL_SOURCE=str(root / "source.c"),
                       WBG_AES_SOURCE_DIR=str(WORK / "src/tiny-AES-c"),
                       MORE_INCDIR=str(WORK / "prefix/include/valgrind"),
                       WBG_EXTRA_AES="1")
            built = subprocess.run(["make", "-j1"], cwd=root, env=env,
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            refused = subprocess.run(["cc", "-DNVALGRIND", "-I" + env["MORE_INCDIR"],
                                      "-c", str(root / "main.c"), "-o", str(root / "disabled.o")],
                                     capture_output=True, timeout=10)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn(b"disabled", refused.stderr)
            self.assertFalse((root / "disabled.o").exists())
            binary = root / "target"
            cipher = AES.new(bytes(range(16)), AES.MODE_ECB)
            for plaintext in [bytes(16), bytes(range(16)), bytes(range(128, 144))]:
                result = subprocess.run([str(binary)], input=plaintext,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, cipher.encrypt(plaintext))
            for invalid in [b"", bytes(15), bytes(17)]:
                result = subprocess.run([str(binary)], input=invalid,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
