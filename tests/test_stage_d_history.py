"""Migration history remains key-free, verifiable and explicit about backend differences."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wbg.config import ANALYSIS_DEFAULTS
from wbg.history_query import query

spec = importlib.util.spec_from_file_location('wbg_export_history', Path(__file__).resolve().parents[1] / 'scripts/export_history.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class MigratedHistoryTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.native = self.root / 'native'
        self.work = self.root / 'container'
        self.project = self.root / 'project'
        self.engine = self.root / 'engine'
        for path in (self.native / 'runs', self.work / 'runs', self.project, self.engine):
            path.mkdir(parents=True)
        self.old_engine = {'source_commits': {'engine': 'same-source'}, 'patch_sha256': 'patch', 'file_sha256': {'binary': 'native-build'}}
        self.current_engine = dict(self.old_engine, file_sha256={'binary': 'container-build'})
        (self.engine / 'baseline.json').write_text(json.dumps(self.current_engine))
        self.config = {'experiment': 'case47', 'target': {'sha256': '47', 'adapter': 'aes128-c', 'abi': 'char-pointer', 'source': '/PRIVATE_SOURCE.c'},
                       'environment': {'backend': 'wsl2-native'}, 'analysis': ANALYSIS_DEFAULTS.copy(),
                       'inputs': {'seed': 1, 'trace_count': 500, 'pilot_count': 50}}
        for index in range(3):
            run = self.native / 'runs' / f'20261026T10000{index}Z-stageB-aaaaaaaa'
            run.mkdir()
            (run / 'effective-config.json').write_text(json.dumps(self.config))
            (run / 'source-lock.json').write_text(json.dumps(self.old_engine))
            (run / 'result.json').write_text(json.dumps({'status': 'verified', 'execution': {'status': 'passed'},
                'recovery': {'status': 'verified', 'holdout_passed': 16}, 'candidate': {'key_hex': 'DO_NOT_EXPORT'}}))
        self.snapshot = self.root / 'snapshot'
        exporter.export(self.native, self.snapshot, {})

    def run_query(self):
        requested = dict(self.config, environment={'backend': 'docker'})
        with patch('wbg.history_query.BACKEND', 'docker'), patch('wbg.history_query.ENGINE_ROOT', self.engine), \
             patch.dict(os.environ, {'WBG_PRIOR_HISTORY': str(self.snapshot)}):
            return query(requested, work=self.work, project=self.project)

    def test_snapshot_preserves_comparison_and_excludes_source_and_candidate(self):
        content = ''.join(path.read_text() for path in self.snapshot.rglob('*') if path.is_file())
        self.assertNotIn('DO_NOT_EXPORT', content)
        self.assertNotIn('PRIVATE_SOURCE', content)
        result = self.run_query()
        self.assertEqual(result['returned'], 3)
        for row in result['records']:
            self.assertEqual(row['holdout_passed'], 16)
            self.assertTrue(row['comparison']['same_pilot_count'])
            self.assertFalse(row['comparison']['same_backend'])
            self.assertFalse(row['comparison']['same_engine'])

    def test_snapshot_tampering_fails_instead_of_querying_unverified_rows(self):
        (self.snapshot / 'index.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            self.run_query()
