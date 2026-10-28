"""Strict schema-2 configuration for the bounded Stage B experiments."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml
from .budgets import authorization
from .workflow import DEFAULTS as BUDGET_DEFAULTS


class ConfigError(ValueError):
    """The requested experiment cannot be run as specified."""


class UnsupportedConfig(ConfigError):
    def __init__(self, reason_code: str, detail: str, evidence: dict | None = None):
        super().__init__(detail)
        self.reason_code = reason_code
        self.evidence = evidence


COMPILE_FLAGS = ["-O2", "-g", "-fno-pie", "-no-pie"]
ANALYSIS_DEFAULTS = {
    "trace_type": "memory_read_values",
    "leakage_model": "hamming_weight",
    "selection_function": "hamming_weight_first",
    "threads": 4,
    "block_size": 128,
    "max_live_blocks": 2,
    "unique_cache_size": 10000,
    "filter_max_row_memory_kib": 1024,
    "leakage_max_row_memory_kib": 8,
    "chunk_key_bytes": 4,
}
RESOURCE_DEFAULTS = {
    "timeout_seconds": None,
    "output_limit_mib": 5120,
    "data_volume_reserve_mib": 20480,
}
PROJECT = Path(__file__).resolve().parents[2]


def _mapping(value: Any, name: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing or unknown:
        raise ConfigError(f"{name}: missing={sorted(missing)}, unknown={sorted(unknown)}")
    if any(not isinstance(key, str) for key in value):
        raise ConfigError(f"{name}: keys must be strings")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _literal(value: Any, name: str, allowed: set[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise ConfigError(f"{name} must be one of {sorted(allowed)}")
    return value


def _capability(value: Any, name: str, allowed: set[str]) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ConfigError(f"{name} must be a capability identifier")
    if value not in allowed:
        raise UnsupportedConfig("unsupported_" + name.rsplit(".", 1)[-1], f"{name}={value} is not implemented")
    return value


def _source(target: dict, config_dir: Path) -> Path:
    name = target["source"]
    if type(name) is not str or not name or "\x00" in name:
        raise ConfigError("target.source must be a nonempty path")
    path = Path(name)
    if not path.is_absolute():
        path = config_dir / path
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ConfigError("target.source must be an existing file")
    expected = target["sha256"]
    if type(expected) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ConfigError("target.sha256 must be a SHA-256 hex digest")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected.lower():
        raise ConfigError(f"target source SHA-256 mismatch: {path}")
    header = path.read_bytes()[:64]
    if header[:4] == b"\x7fELF":
        little = len(header) > 5 and header[5] == 1
        raise UnsupportedConfig("input_format_elf", "current adapter accepts C source, not ELF", {
            "path": str(path), "sha256": actual, "bytes": path.stat().st_size,
            "elf_class": header[4], "endianness": header[5],
            "e_machine": int.from_bytes(header[18:20], "little" if little else "big"),
            "target_process_started": False})
    if path.suffix.lower() != ".c":
        raise UnsupportedConfig("input_format", "current adapter requires C source")
    return path


def normalize(raw: Any, config_dir: Path) -> dict:
    """Reject unsupported fields and return the values the runner must use."""
    root = _mapping(raw, "root", {"schema_version", "experiment", "environment", "target", "inputs", "analysis", "resources"}, {"budget"})
    if type(root["schema_version"]) is not int or root["schema_version"] != 2:
        raise ConfigError("schema_version must be 2")
    experiment = root["experiment"]
    if type(experiment) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", experiment):
        raise ConfigError("experiment must be a short safe identifier")
    environment = _mapping(root["environment"], "environment", {"backend", "distribution"})
    _capability(environment["backend"], "environment.backend", {"wsl2-native", "docker"})
    _literal(environment["distribution"], "environment.distribution", {"Ubuntu-22.04"})

    target = _mapping(root["target"], "target", {"adapter", "abi", "source", "sha256", "compile_flags"}, {"fixture"})
    _capability(target["adapter"], "target.adapter", {"aes128-c"})
    _capability(target["abi"], "target.abi", {"unsigned-char-pointer", "char-pointer"})
    if target.get("fixture") is not None:
        _literal(target["fixture"], "target.fixture", {"ordinary-aes128"})
    if type(target["compile_flags"]) is not list or target["compile_flags"] != COMPILE_FLAGS:
        raise ConfigError("target.compile_flags must match the Stage B verified flag list")
    source = _source(target, config_dir)

    inputs = _mapping(root["inputs"], "inputs", {"generator", "seed", "pilot_count", "trace_count", "holdout_count"})
    _literal(inputs["generator"], "inputs.generator", {"sha256-counter-v1"})
    _integer(inputs["seed"], "inputs.seed", 0, 2**64 - 1)
    _integer(inputs["trace_count"], "inputs.trace_count", 10, 500)
    pilot_count = (max(10, (inputs["trace_count"] + 9) // 10)
                   if inputs["pilot_count"] == "auto" else inputs["pilot_count"])
    _integer(pilot_count, "inputs.pilot_count", 10, inputs["trace_count"])
    _integer(inputs["holdout_count"], "inputs.holdout_count", 16, 16)

    analysis = _mapping(root["analysis"], "analysis", set(ANALYSIS_DEFAULTS))
    for key in ("trace_type", "leakage_model", "selection_function"):
        _capability(analysis[key], f"analysis.{key}", {ANALYSIS_DEFAULTS[key]})
    for key, high in {"threads": 4, "block_size": 128, "max_live_blocks": 2,
                      "unique_cache_size": 10000, "filter_max_row_memory_kib": 1024,
                      "leakage_max_row_memory_kib": 8, "chunk_key_bytes": 4}.items():
        _integer(analysis[key], f"analysis.{key}", 1, high)

    resources = _mapping(root["resources"], "resources", set(RESOURCE_DEFAULTS))
    grant = authorization(root)
    if resources["timeout_seconds"] is not None:
        _integer(resources["timeout_seconds"], "resources.timeout_seconds", 1,
                 grant["max_total_seconds"] if grant and grant["max_total_seconds"] is not None else 1800)
    _integer(resources["output_limit_mib"], "resources.output_limit_mib", 1,
             grant["max_total_output_bytes"] // 2**20 if grant else 5120)
    _integer(resources["data_volume_reserve_mib"], "resources.data_volume_reserve_mib", 20480, 20480)
    defaults = BUDGET_DEFAULTS.copy()
    budget = _mapping(root.get("budget", defaults), "budget", set(BUDGET_DEFAULTS))
    for key in BUDGET_DEFAULTS:
        if budget[key] is not None:
            _integer(budget[key], "budget." + key, 1, 86400)
    if (budget["probe_timeout_seconds"] is not None and resources["timeout_seconds"] is not None and
            budget["probe_timeout_seconds"] > resources["timeout_seconds"]):
        raise ConfigError("probe timeout cannot exceed the explicit run timeout")

    effective = copy.deepcopy(root)
    effective["target"]["source"] = str(source)
    effective["target"]["sha256"] = target["sha256"].lower()
    effective["inputs"]["pilot_count"] = pilot_count
    effective["budget"] = copy.deepcopy(budget)
    return effective


def load(path: Path) -> tuple[dict, dict]:
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ConfigError("config is not a file")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc
    return raw, normalize(raw, path.parent)


def demo() -> tuple[dict, dict]:
    from .runtime import BACKEND
    source = PROJECT / "fixtures" / "ordinary-aes128" / "adapter.c"
    raw = {
        "schema_version": 2,
        "experiment": "ordinary-aes-100",
        "environment": {"backend": BACKEND, "distribution": "Ubuntu-22.04"},
        "target": {"adapter": "aes128-c", "abi": "unsigned-char-pointer",
                   "fixture": "ordinary-aes128", "source": str(source),
                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "compile_flags": COMPILE_FLAGS.copy()},
        "inputs": {"generator": "sha256-counter-v1", "seed": 20261023,
                   "pilot_count": "auto", "trace_count": 100, "holdout_count": 16},
        "analysis": ANALYSIS_DEFAULTS.copy(),
        "resources": RESOURCE_DEFAULTS.copy(),
    }
    return raw, normalize(raw, PROJECT)


def to_yaml(value: dict) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
