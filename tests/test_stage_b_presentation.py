"""Regression for meaningful user-visible estimates and resource names."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('report_progress', Path(__file__).parents[1] / 'scripts/report_progress.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PresentationTests(unittest.TestCase):
    def test_estimate_uses_remaining_compute_not_pilot_or_wait(self):
        value = module.report({'status': 'awaiting_decision', 'progress': {'stage': 'awaiting_formal_approval'}},
                              [{'run_id': 'a', 'seconds': 382.887}, {'run_id': 'b', 'seconds': 392.715}])
        self.assertEqual(value['remaining_compute_seconds'], 388)
        self.assertIn('6.5 分钟', module.render(value))

    def test_resources_named_and_internal_allowance_hidden(self):
        value = module.report({'space': {'estimated_additional_bytes': 2 * 2**30,
                                         'authorized_output_limit_bytes': 5 * 2**30, 'occupied_bytes': 100},
                               'observations': {'logical_output_bytes': 3 * 2**30}}, [])
        self.assertIn('硬盘占用约 2.0 GiB', module.render(value))
        self.assertIn('任务硬盘文件约 3.0 GiB', module.render(value))
        self.assertNotIn('authorized_output_limit_bytes', str(value))
        self.assertNotIn('occupied_bytes', str(value))

    def test_unknown_or_inflight_does_not_invent_a_narrow_countdown(self):
        value = module.report({'status': 'running', 'progress': {'stage': 'formal-cpa'},
                               'estimated_remaining_seconds': {'low': 0, 'high': 1000}}, [{'seconds': 300}])
        self.assertIsNone(value['remaining_compute_seconds'])
        self.assertIn('暂无法可靠估计', module.render(value))

    def test_only_actionable_resource_problem_is_shown(self):
        value = module.report({'space': {'estimate_exceeds_allowance': True}}, [])
        self.assertEqual(value['action_required'], 'disk_storage_choice_needed')

    def test_terminal_has_no_remaining_disk_or_time_claim(self):
        value = module.report({'status': 'verified', 'space': {'estimated_additional_bytes': 123}}, [])
        self.assertNotIn('disk_storage', value)

    def test_history_rejects_other_targets_future_runs_and_rough_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / '20261026T120000Z-stageB-12345678'
            run.mkdir()
            config = {'target': {'sha256': '47'}, 'environment': {'backend': 'wsl2-native'},
                      'analysis': {'threads': 4}, 'inputs': {'seed': 1, 'trace_count': 500}}
            lock = {'files': [{'path': 'worker.py', 'sha256': 'frozen'}]}
            (run / 'effective-config.json').write_text(json.dumps(config))
            (run / 'orchestrator-lock.json').write_text(json.dumps(lock))
            for n, target, timestamp, basis in [('good', '47', '110000', 'same-boot completion observer'),
                    ('other', '82', '110001', 'same-boot completion observer'),
                    ('future', '47', '130000', 'same-boot completion observer'),
                    ('rough', '47', '110002', 'rough UTC conversion')]:
                d = root / ('seed' + n)
                d.mkdir()
                other = json.loads(json.dumps(config))
                other['inputs']['seed'] = 2
                other['target']['sha256'] = target
                (d / 'effective-config.json').write_text(json.dumps(other))
                (d / 'orchestrator-lock.json').write_text(json.dumps(lock))
                (d / 'completion-audit.json').write_text(json.dumps({'run_id': f'20261026T{timestamp}Z-stageB-11111111',
                    'status': 'verified', 'manifest_mismatches': [], 'runtime_matches_frozen_implementation': True,
                    'estimate_comparison': {'post_confirmation_compute_seconds': 388, 'timing_basis': basis}}))
            values = module.history(run, root)
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0]['seconds'], 388)


if __name__ == '__main__':
    unittest.main()
