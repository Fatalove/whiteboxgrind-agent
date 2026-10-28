import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from wbg.runtime import host_resources


class PhysicalResourcesTest(unittest.TestCase):
    def test_dotnet_seven_digit_fraction_is_accepted_on_python310(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'host.json'
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + '7+00:00'
            path.write_text(json.dumps({'schema_version': 1, 'recorded_at_utc': stamp,
                                       'work_free_bytes': 30 * 2**30, 'export_free_bytes': 25 * 2**30}))
            self.assertEqual(host_resources(path)['work_free_bytes'], 30 * 2**30)

    def test_fresh_actual_volumes_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'host.json'
            document = {'schema_version': 1, 'recorded_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'work_free_bytes': 30 * 2**30, 'export_free_bytes': 25 * 2**30}
            path.write_text(json.dumps(document))
            self.assertEqual(host_resources(path)['export_free_bytes'], 25 * 2**30)

    def test_stale_observation_and_boolean_capacity_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'host.json'
            document = {'schema_version': 1, 'recorded_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'work_free_bytes': True, 'export_free_bytes': 25 * 2**30}
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                host_resources(path)
            document.update(work_free_bytes=30 * 2**30, recorded_at_utc='2000-01-01T00:00:00+00:00')
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'stale'):
                host_resources(path)
