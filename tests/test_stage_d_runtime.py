"""Container limits must describe cgroups, independent of host /proc figures."""
import tempfile
from pathlib import Path
import unittest

from wbg.runtime import container_limits


class ContainerLimitsTest(unittest.TestCase):
    def write(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value))

    def test_v2_finite_quotas_and_available_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in {"memory.max": 4 * 2**30, "memory.current": 2**30,
                               "memory.swap.max": 2**30, "cpu.max": "200000 100000"}.items():
                self.write(root, key, value)
            value = container_limits(root)
            self.assertEqual(value["cpu_limit"], 2)
            self.assertEqual(value["memory_available_bytes"], 3 * 2**30)
            self.assertEqual(value["swap_limit_bytes"], 2**30)

    def test_inactive_file_cache_is_not_treated_as_unreclaimable_working_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in {"memory.max": 4 * 2**30, "memory.current": 4 * 2**30,
                               "memory.stat": 'inactive_file 1073741824\nanon 3221225472\n',
                               "memory.swap.max": 2**30, "cpu.max": "200000 100000"}.items():
                self.write(root, key, value)
            self.assertEqual(container_limits(root)['memory_available_bytes'], 2**30)

    def test_v2_unlimited_is_unknown_not_a_large_finite_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in {"memory.max": "max", "memory.current": 10,
                               "memory.swap.max": "max", "cpu.max": "max 100000"}.items():
                self.write(root, key, value)
            value = container_limits(root)
            self.assertIsNone(value["cpu_limit"])
            self.assertIsNone(value["memory_available_bytes"])

    def test_v1_memsw_is_total_memory_plus_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in {"memory/memory.limit_in_bytes": 4 * 2**30,
                               "memory/memory.usage_in_bytes": 5 * 2**30,
                               "memory/memory.memsw.limit_in_bytes": 5 * 2**30,
                               "cpu/cpu.cfs_quota_us": 200000, "cpu/cpu.cfs_period_us": 100000}.items():
                self.write(root, key, value)
            value = container_limits(root)
            self.assertEqual(value["memory_available_bytes"], 0)
            self.assertEqual(value["swap_limit_bytes"], 2**30)

    def test_malformed_limits_do_not_become_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "memory.max", "invalid")
            self.write(root, "cpu.max", "200000 100000")
            with self.assertRaises(ValueError):
                container_limits(root)


if __name__ == "__main__":
    unittest.main()
