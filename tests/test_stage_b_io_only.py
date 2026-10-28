"""Real Valgrind I/O-only vs full event capture; fixture data is not recovery proof."""
from pathlib import Path
import tempfile
import unittest

from Crypto.Cipher import AES

from wbg.config import demo
from wbg.execution import _prepare
from wbg.worker import Worker
from wbg.runtime import ENGINE_ROOT


class IOOnlyTests(unittest.TestCase):
    def test_lightweight_io_matches_native_and_full_capture(self):
        requested, effective = demo()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _prepare(root, requested, effective, {'test_only': True})
            (root / 'tmp').mkdir()
            worker = Worker(root)
            import os
            env = dict(os.environ, WBG_ORIGINAL_SOURCE=str(root / 'target/source.c'),
                       WBG_AES_SOURCE_DIR=str(ENGINE_ROOT/'src/tiny-AES-c'),
                       WBG_EXTRA_AES='1', MORE_INCDIR=str(ENGINE_ROOT/'prefix/include/valgrind'))
            worker.command('test-build', ['make', '-j1'], cwd=root / 'target', env=env)
            blocks = [bytes(16), bytes(range(16)), bytes(range(128, 144))]
            rows, light = worker.native(root / 'target/target', blocks, 'light', instrumented=True)
            self.assertTrue(all(row['exit_code'] == 0 for row in rows))
            self.assertEqual(light, [AES.new(bytes(range(16)), AES.MODE_ECB).encrypt(x) for x in blocks])
            inputs = root / 'io-inputs.bin'; inputs.write_bytes(b''.join(blocks))
            _, full, _ = worker.trace('full-comparison', inputs)
            self.assertEqual(light, full)


if __name__ == '__main__': unittest.main()
