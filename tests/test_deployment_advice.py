"""Docker planning uses the fresh Windows volume, not native or virtual space."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wbg import resource_advice as module

class DeploymentAdviceTests(unittest.TestCase):
    def test_docker_uses_fresh_mapping_over_other_host_estimates(self):
        physical={'work_drive':'D:','export_drive':'D:','work_free_bytes':50*2**30,'export_free_bytes':50*2**30}
        host={'memory_available_bytes':8*2**30,'wsl_storage_drive':'D','export_drive':'D','volumes':{'D':{'free_bytes':9000*2**30}}}
        with patch.object(module,'BACKEND','docker'), patch.object(module,'host_resources',return_value=physical), \
             patch.object(module,'container_limits',return_value={'memory_available_bytes':3*2**30}), \
             patch.object(module,'memory_info',return_value={'MemAvailable':3*2**30}), \
             patch.object(module.shutil,'disk_usage',return_value=SimpleNamespace(free=9000*2**30)):
            result=module.advice(host)
        self.assertEqual(result['suggested_additional_output_bytes'],18*2**30)
        self.assertEqual(result['suggested_memory_bytes'],3*2**30-512*2**20)
        self.assertTrue(result['shared_physical_volume'])
