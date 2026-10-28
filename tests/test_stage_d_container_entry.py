import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from wbg import container_entry


class ContainerEntryTest(unittest.TestCase):
    def configuration(self, root, backend='docker'):
        path = root / 'host-config.json'
        path.write_text(json.dumps({'schema_version': 2, 'environment': {'backend': backend},
                                   'target': {'source': '../host-source.c', 'sha256': 'a' * 64,
                                              'candidate': 'must_not_be_exposed'}}))
        return path

    def test_metadata_does_not_disclose_extra_target_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.configuration(Path(directory))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(container_entry.main(['metadata', str(path)]), 0)
            self.assertNotIn('candidate', json.loads(output.getvalue())['target'])

    def test_remapping_preserves_original_config_and_requires_explicit_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.configuration(root)
            before = path.read_bytes()
            received = []
            fake = types.SimpleNamespace(main=lambda args: received.extend(args) or 0)
            with patch.object(container_entry, 'WORK_ROOT', root / 'work'), patch.dict(sys.modules, {'wbg.cli': fake}), patch.dict(os.environ):
                container_entry.main(['analyze', '--config', str(path), '--out', '/exports/new', '--json'])
            mounted = json.loads(Path(received[received.index('--config') + 1]).read_text())
            self.assertEqual(mounted['target']['source'], '/inputs/source.c')
            self.assertEqual(path.read_bytes(), before)
            native = self.configuration(root, 'wsl2-native')
            with self.assertRaisesRegex(ValueError, 'explicitly configured'):
                container_entry.main(['metadata', str(native)])

    def test_malformed_root_does_not_become_an_unstructured_attribute_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.yaml'
            path.write_text('[]')
            with self.assertRaises(ValueError):
                container_entry.main(['metadata', str(path)])
