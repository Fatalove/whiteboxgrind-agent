"""Destructive-operation guards on disposable synthetic data only."""
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from wbg import retention

class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)
        self.run=self.work/'runs/20261028T000000Z-stageB-aaaaaaaa';self.run.mkdir(parents=True)
        (self.run/'result.json').write_text(json.dumps({'run_id':self.run.name,'status':'cancelled'}))
        (self.run/'accounting.json').write_text('{"elapsed_seconds":12,"output_bytes":999}')
        (self.run/'raw').mkdir();(self.run/'raw/trace.y5').write_bytes(b'raw')
        (self.run/'inputs').mkdir();(self.run/'inputs/holdout.bin').write_bytes(b'holdout')

    def test_no_reply_and_plan_never_delete(self):
        payload=retention.plan(self.run,self.work)
        self.assertEqual(payload['default'],'all')
        self.assertTrue((self.run/'raw/trace.y5').exists())

    def test_evidence_policy_preserves_accounting_and_is_one_use(self):
        before=(self.run/'accounting.json').read_bytes()
        payload=retention.plan(self.run,self.work)
        retention.apply(self.run,self.work,payload['plan_id'],'evidence','TEST user chose evidence')
        self.assertFalse((self.run/'raw/trace.y5').exists())
        self.assertTrue((self.run/'inputs/holdout.bin').exists())
        self.assertEqual(before,(self.run/'accounting.json').read_bytes())
        with self.assertRaises(ValueError):retention.apply(self.run,self.work,payload['plan_id'],'minimal','TEST')

    def test_modified_files_wrong_run_and_no_choice_refused(self):
        payload=retention.plan(self.run,self.work)
        with self.assertRaises(ValueError):retention.apply(self.run,self.work,payload['plan_id'],'minimal','')
        (self.run/'raw/trace.y5').write_bytes(b'changed')
        with self.assertRaises(ValueError):retention.apply(self.run,self.work,payload['plan_id'],'minimal','TEST')
        self.assertTrue((self.run/'raw/trace.y5').exists())

    def test_running_global_lock_refuses_cleanup(self):
        with (self.work/'.stage-b.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(ValueError):retention.plan(self.run,self.work)

    def test_all_terminal_states_offer_choice(self):
        for status in ('verified','no_key','unsupported','resource_limit','error','cancelled','probe_completed'):
            (self.run/'result.json').write_text(json.dumps({'run_id':self.run.name,'status':status}))
            self.assertTrue(retention.plan(self.run,self.work)['decision_required'])

    def test_symlink_refused(self):
        (self.run/'link').symlink_to(self.work)
        with self.assertRaises(ValueError):retention.plan(self.run,self.work)

    def test_a_later_choice_preserves_previous_receipt(self):
        first=retention.plan(self.run,self.work)
        retention.apply(self.run,self.work,first['plan_id'],'all','TEST keep all')
        second=retention.plan(self.run,self.work)
        retention.apply(self.run,self.work,second['plan_id'],'minimal','TEST choose minimal later')
        receipt=json.loads((self.run/'retention.json').read_text())
        self.assertEqual(receipt['previous']['choice'],'all')
        self.assertEqual(receipt['previous']['plan_id'],first['plan_id'])

    def test_export_policy_cannot_remove_accounting(self):
        export=self.work/'export';export.mkdir()
        (export/'result.json').write_bytes((self.run/'result.json').read_bytes())
        (export/'evidence').mkdir()
        (export/'evidence/accounting.json').write_bytes((self.run/'accounting.json').read_bytes())
        (export/'evidence/cpa.csv').write_bytes(b'synthetic')
        payload=retention.plan(self.run,self.work,export)
        retention.apply(self.run,self.work,payload['plan_id'],'minimal','TEST explicit minimal',export)
        self.assertTrue((export/'evidence/accounting.json').exists())
        self.assertFalse((export/'evidence/cpa.csv').exists())
