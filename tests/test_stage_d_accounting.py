"""Migrating backends must preserve prior consumption and explicit deadlines."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wbg import execution


class ImportedAccountingTest(unittest.TestCase):
    def fixture(self, root, *, limit=None, digest='a' * 64, duplicate=False):
        row = {'run_id': '20261026T000000Z-stageB-aaaaaaaa', 'group': 'migration-test:1',
               'target_sha256': digest, 'group_max_seconds': limit,
               'group_max_output_bytes': 5120 * 2**20, 'elapsed_seconds': 90,
               'occupied_bytes': 128 * 2**20, 'unfinished': False}
        ledger = root / 'prior.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'records': [row, row] if duplicate else [row]}))
        config = {'experiment': 'migration-test', 'inputs': {'seed': 1}, 'target': {'sha256': 'a' * 64},
                  'resources': {'timeout_seconds': None, 'output_limit_mib': 5120}}
        return ledger, config

    def test_imported_time_and_disk_are_deducted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger, config = self.fixture(root)
            with patch.object(execution, 'WORK', root), patch.dict(os.environ, WBG_PRIOR_ACCOUNTING=str(ledger)):
                adjusted, record = execution._remaining_budget(config)
            self.assertEqual(adjusted['resources']['output_limit_mib'], 4992)
            self.assertEqual(record['prior_elapsed_seconds'], 90)
            self.assertEqual(record['prior_output_bytes'], 128 * 2**20)
            self.assertEqual(len(record['prior_run_ids']), 1)

    def test_migration_cannot_remove_an_old_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger, config = self.fixture(root, limit=1800)
            with patch.object(execution, 'WORK', root), patch.dict(os.environ, WBG_PRIOR_ACCOUNTING=str(ledger)):
                with self.assertRaisesRegex(ValueError, 'deadline'):
                    execution._remaining_budget(config)

    def test_target_conflicts_and_duplicate_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for options in ({'digest': 'b' * 64}, {'duplicate': True}):
                ledger, config = self.fixture(root, **options)
                with patch.object(execution, 'WORK', root), patch.dict(os.environ, WBG_PRIOR_ACCOUNTING=str(ledger)):
                    with self.assertRaises(ValueError):
                        execution._remaining_budget(config)
