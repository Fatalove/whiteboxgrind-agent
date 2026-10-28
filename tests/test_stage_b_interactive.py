"""User-controlled timing and stage gates, with actual small worker processes."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wbg import execution, monitor, workflow
from wbg.config import demo, load, normalize, PROJECT
from wbg.protocol import atomic_json
from wbg.resource_advice import advice


def small_quote():
    return workflow.quote([{'name': 'pilot-' + x, 'elapsed_seconds': 0.01}
                           for x in ('collect', 'filter', 'unique', 'leakage', 'cpa')], 10, 100, 1000, 1000, 10 * 2**20)


class InteractiveTests(unittest.TestCase):
    def setUp(self):
        from support import configure
        configure(self)

    def test_completed_cpa_does_not_consume_validation_time_while_waiting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); now = time.monotonic()
            atomic_json(root / 'stage.json', {'stage': 'formal-cpa', 'at_monotonic': now - 1000})
            atomic_json(root / 'commands.json', {'commands': [{'name': x} for x in workflow.STAGES]})
            left, _ = workflow.remaining(root, small_quote(), now)
            self.assertEqual(left, {'low': 0, 'high': 60})

    def test_none_deadlines_and_historical_consumption_are_preserved(self):
        raw, effective = load(self.test_config)
        self.assertIsNone(effective['resources']['timeout_seconds'])
        self.assertTrue(all(v is None for v in effective['budget'].values()))
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder); prior = work / 'runs/20261026T000000Z-stageB-aaaaaaaa'; prior.mkdir(parents=True)
            atomic_json(prior / 'budget-group.json', {'group': 'synthetic-budget-case:20261023', 'run_id': prior.name,
                        'group_max_seconds': 7200, 'group_max_output_bytes': 5120 * 2**20})
            atomic_json(prior / 'accounting.json', {'elapsed_seconds': 642.248})
            (prior / 'occupied.bin').write_bytes(bytes(1024))
            with patch.object(execution, 'WORK', work):
                adjusted, group = execution._remaining_budget(effective)
            self.assertIsNone(adjusted['resources']['timeout_seconds'])
            self.assertEqual(group['original_group_max_seconds'], 7200)
            self.assertEqual(group['prior_elapsed_seconds'], 642.248)
            self.assertGreater(group['prior_output_bytes'], 1024)
            self.assertEqual(group['time_policy'], 'user_controlled')

    def test_stage_boundary_waits_without_restarting_and_old_windows_do_not_expire(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); atomic_json(root / 'estimate.json', small_quote())
            state = {}; now = time.monotonic()
            workflow.tick(root, state, workflow.DEFAULTS, now, None)
            token = workflow.read(root, 'progress.json')['decision']['checkpoint_id']
            self.assertIsNone(workflow.read(root, 'progress.json')['decision']['deadline_monotonic'])
            # Advance past both former reply deadlines without any permission.
            self.assertIsNone(workflow.tick(root, state, workflow.DEFAULTS, now + 400, None))
            self.assertEqual(workflow.read(root, 'progress.json')['decision']['checkpoint_id'], token)
            code = ('from pathlib import Path; from wbg.workflow import enter_stage; '
                    f"r=Path({str(root)!r}); enter_stage(r,'next-native-stage'); "
                    "(r/'started-once').write_text('one')")
            worker = subprocess.Popen([sys.executable, '-c', code])
            try:
                until = time.monotonic() + 3
                while not (root / 'boundary-state.json').exists() and time.monotonic() < until: time.sleep(0.01)
                self.assertTrue(workflow.read(root, 'boundary-state.json')['waiting'])
                self.assertFalse((root / 'started-once').exists())
                self.assertFalse((root / 'stage.json').exists())
                workflow.decide(root, token, 'continue')
                workflow.tick(root, state, workflow.DEFAULTS, time.monotonic(), None)
                worker.wait(timeout=3)
                self.assertEqual(worker.returncode, 0)
                self.assertEqual((root / 'started-once').read_text(), 'one')
                self.assertGreater(workflow.waiting_seconds(root, time.monotonic()), 0)
            finally:
                if worker.poll() is None: worker.kill(); worker.wait()

    def test_no_run_deadline_still_cleans_on_explicit_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); marker = root / 'cancel.request'
            timer = threading.Timer(1.2, lambda: marker.write_text('test-only cancel'))
            timer.start()
            try:
                record = monitor.run([sys.executable, '-c', 'import time; time.sleep(10)'], run_root=root,
                    log_dir=root / 'logs', timeout_seconds=None, output_limit_mib=10, reserve_mib=0,
                    cancel_marker=marker, budget_policy=workflow.DEFAULTS)
            finally: timer.cancel(); timer.join()
            self.assertEqual(record['trigger']['kind'], 'explicit_cancel_marker')
            self.assertIsNone(record['initial_timeout_seconds'])
            self.assertFalse(monitor._group_members(record['process_group']))

    def test_disk_advice_uses_physical_mapping_once_not_virtual_terabytes(self):
        host = {'memory_available_bytes': 8 * 2**30, 'wsl_storage_drive': 'D', 'export_drive': 'D',
                'volumes': {'D': {'free_bytes': 50 * 2**30}}}
        with patch('wbg.resource_advice.BACKEND','wsl2-native'), patch('wbg.resource_advice.memory_info', return_value={'MemAvailable': 3 * 2**30}):
            result = advice(host)
            unknown = advice({})
        self.assertEqual(result['suggested_additional_output_bytes'], 18 * 2**30)
        self.assertEqual(result['suggested_memory_bytes'], 3 * 2**30 - 512 * 2**20)
        self.assertTrue(result['shared_physical_volume'])
        self.assertIsNone(unknown['suggested_additional_output_bytes'])

    def test_cancel_api_uses_active_run_identity_and_never_guesses_another_run(self):
        from wbg.cli import main
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder); run_id = '20261026T000000Z-stageB-aaaaaaaa'
            run = work / 'runs' / run_id; run.mkdir(parents=True)
            stat = Path('/proc/self/stat').read_text()
            atomic_json(work / 'active.json', {'run_id': run_id, 'pid': os.getpid(), 'launch_token': 'a' * 32,
                'start_ticks': int(stat[stat.rfind(')') + 2:].split()[19]),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
            with patch.object(execution, 'WORK', work), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['cancel', '--run-id', run_id]), 0)
                self.assertEqual(main(['cancel', '--run-id', '20261026T000000Z-stageB-bbbbbbbb']), 40)
            self.assertEqual(workflow.read(run, 'cancel.request')['source'], 'agent_cancel')


if __name__ == '__main__': unittest.main()
