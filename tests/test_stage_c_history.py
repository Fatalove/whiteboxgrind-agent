import copy
import json
from pathlib import Path
import tempfile
import unittest

from wbg.history_query import query


class HistoryQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work, self.data, self.project = [self.root / x for x in ('work', 'data', 'project')]
        (self.work / 'runs').mkdir(parents=True)
        (self.project / 'experiments/locks').mkdir(parents=True)
        self.config = {'experiment': 'case', 'target': {'sha256': '47', 'adapter': 'aes128-c', 'abi': 'char-pointer'},
                       'environment': {'backend': 'wsl2-native'}, 'analysis': {'model': 'hw'},
                       'inputs': {'seed': 1, 'trace_count': 500, 'pilot_count': 50}}
        self.engine = {'source_commits': {'engine': 'a'}, 'patch_sha256': 'b', 'file_sha256': {'binary': 'c'}}
        (self.project / 'experiments/locks/stage-b-environment.json').write_text(json.dumps(self.engine))

    def add(self, name, *, status='verified', target='47', diagnostic=False, pilot=50):
        r = self.work / 'runs' / name
        r.mkdir()
        cfg = copy.deepcopy(self.config)
        cfg['target']['sha256'] = target
        cfg['inputs']['pilot_count'] = pilot
        (r / 'effective-config.json').write_text(json.dumps(cfg))
        (r / 'source-lock.json').write_text(json.dumps(self.engine))
        (r / 'result.json').write_text(json.dumps({'status': status, 'execution': {'status': 'passed'},
            'recovery': {'status': status, 'holdout_passed': 16}, 'candidate': {'key_hex': 'SECRET'}}))
        if diagnostic:
            (r / 'operation.json').write_text(json.dumps({'command': 'probe'}))

    def run_query(self, limit=5):
        return query(self.config, limit, work=self.work, data=self.data, project=self.project)

    def test_both_success_and_failure_are_returned_without_answers(self):
        self.add('20261026T100000Z-stageB-aaaaaaaa')
        self.add('20261026T110000Z-stageB-bbbbbbbb', status='no_key')
        value = self.run_query()
        self.assertEqual({r['status'] for r in value['records']}, {'verified', 'no_key'})
        self.assertNotIn('SECRET', json.dumps(value))
        self.assertNotIn('candidate', json.dumps(value))
        self.assertTrue(all(r['comparison']['hardware_match'] is None for r in value['records']))

    def test_diagnostics_and_other_targets_are_excluded(self):
        self.add('a-stageB-test', diagnostic=True)
        self.add('b-stageB-test', target='82')
        self.assertEqual(self.run_query()['returned'], 0)

    def test_five_record_cap_and_scale_ranking(self):
        for n in range(7):
            self.add(f'20261026T10000{n}Z-stageB-aaaaaaaa', pilot=10)
        self.add('20261026T090000Z-stageB-bbbbbbbb', pilot=50)
        value = self.run_query()
        self.assertEqual(value['returned'], 5)
        self.assertTrue(value['records'][0]['comparison']['same_pilot_count'])
        for n in (0, 6, True):
            with self.assertRaises(ValueError): self.run_query(n)

    def test_unknown_identity_does_not_match(self):
        self.add('a-stageB-test')
        self.config['target'] = {}
        self.assertEqual(self.run_query()['returned'], 0)


if __name__ == '__main__':
    unittest.main()
