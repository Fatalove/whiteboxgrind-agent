"""Contract checks for configuration and deterministic input materialization."""

import copy
from pathlib import Path
import tempfile
import unittest

from wbg.config import ConfigError, demo, load, normalize
from wbg.inputs import generate


class StageBConfigTest(unittest.TestCase):
    def test_unimplemented_capability_is_distinct_from_malformed_config(self):
        from wbg.config import demo, normalize, UnsupportedConfig, ConfigError, PROJECT
        requested, _ = demo()
        requested["analysis"]["selection_function"] = "last_round"
        with self.assertRaises(UnsupportedConfig): normalize(requested, PROJECT)
        requested["analysis"]["selection_function"] = 9
        with self.assertRaises(ConfigError) as context: normalize(requested, PROJECT)
        self.assertNotIsInstance(context.exception, UnsupportedConfig)
    def test_requested_seed_and_trace_count_change_actual_input(self):
        raw, base = demo()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = generate(root / "first", base)
            changed = copy.deepcopy(raw)
            changed["inputs"]["seed"] = 20261024
            changed["inputs"]["trace_count"] = 10
            second = generate(root / "second", normalize(changed, root))
            self.assertEqual(first["files"]["analysis.bin"]["blocks"], 100)
            self.assertEqual(second["files"]["analysis.bin"]["blocks"], 10)
            self.assertNotEqual(first["files"]["analysis.bin"]["sha256"],
                                second["files"]["analysis.bin"]["sha256"])
            self.assertTrue(first["holdout_disjoint_from_analysis"])
            self.assertTrue(second["holdout_disjoint_from_analysis"])

    def test_rejects_unknown_field_bool_seed_and_changed_source(self):
        raw, _ = demo()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bad = copy.deepcopy(raw)
            bad["analysis"]["ignored_parameter"] = 1
            with self.assertRaises(ConfigError):
                normalize(bad, root)
            bad = copy.deepcopy(raw)
            bad["inputs"]["seed"] = True
            with self.assertRaises(ConfigError):
                normalize(bad, root)
            bad = copy.deepcopy(raw)
            source = root / "target.c"
            source.write_text("void x(void) {}\n", encoding="utf-8")
            bad["target"]["source"] = str(source)
            with self.assertRaises(ConfigError):
                normalize(bad, root)

    def test_unsafe_yaml_constructor_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "target.yaml"
            path.write_text("!!python/object/apply:os.system ['false']\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load(path)


if __name__ == "__main__":
    unittest.main()
