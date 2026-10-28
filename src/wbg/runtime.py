"""Deployment-owned paths and effective container limits; native defaults stay stable."""
from __future__ import annotations

import os
import datetime as dt
import json
import re
from pathlib import Path
import shutil

BACKEND = os.environ.get("WBG_RUNTIME_BACKEND", "wsl2-native")
ENGINE_ROOT = Path(os.environ.get("WBG_ENGINE_ROOT", "/home/wbg/whiteboxgrind-work"))
WORK_ROOT = Path(os.environ.get("WBG_WORK_ROOT", str(ENGINE_ROOT)))


def host_resources(path: Path | None = None, *, max_age=30) -> dict:
    """A fresh host measurement is required; a sparse container volume is not physical free space."""
    value = path or Path(os.environ.get('WBG_HOST_RESOURCES', '/provenance/host-resources.json'))
    record = json.loads(value.read_text(encoding='utf-8-sig'))
    if record.get('schema_version') != 1:
        raise ValueError('invalid host resource schema')
    # .NET's round-trip ISO format has seven fractional digits; Python 3.10 accepts six.
    stamp_text = re.sub(r'(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)', r'\1', record['recorded_at_utc'])
    stamp = dt.datetime.fromisoformat(stamp_text.replace('Z', '+00:00'))
    age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
    if age > max_age or age < -10:
        raise ValueError('host physical resource observation is stale or future-dated')
    for key in ('work_free_bytes', 'export_free_bytes'):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError('invalid physical free-space observation')
    return record


def data_free_bytes() -> int:
    if BACKEND == 'docker':
        record = host_resources()
        return min(record['work_free_bytes'], record['export_free_bytes'])
    return shutil.disk_usage('/mnt/d').free


def _number(path: Path) -> int | None:
    value = path.read_text().strip()
    if value == "max":
        return None
    result = int(value)
    return None if result >= 2**60 else result


def container_limits(root: Path = Path("/sys/fs/cgroup")) -> dict:
    """Read v2 or v1 cgroup limits, rather than treating /proc as container quotas."""
    if (root / "memory.max").is_file():
        quota, period = (root / "cpu.max").read_text().split()
        limit = _number(root / "memory.max")
        used = _number(root / "memory.current")
        stats = dict(line.split() for line in (root / 'memory.stat').read_text().splitlines()) if (root / 'memory.stat').is_file() else {}
        inactive = int(stats.get('inactive_file', 0))
        return {"version": 2, "memory_limit_bytes": limit, "memory_current_bytes": used,
                "inactive_file_bytes": inactive,
                "memory_available_bytes": max(0, min(limit, limit - used + inactive)) if limit is not None and used is not None else None,
                "swap_limit_bytes": _number(root / "memory.swap.max"),
                "cpu_limit": int(quota) / int(period) if quota != "max" else None}
    memory = root / "memory"
    cpu = root / "cpu"
    limit = _number(memory / "memory.limit_in_bytes")
    used = _number(memory / "memory.usage_in_bytes")
    stats = dict(line.split() for line in (memory / 'memory.stat').read_text().splitlines()) if (memory / 'memory.stat').is_file() else {}
    inactive = int(stats.get('total_inactive_file', 0))
    memsw = _number(memory / "memory.memsw.limit_in_bytes")
    quota = int((cpu / "cpu.cfs_quota_us").read_text())
    period = int((cpu / "cpu.cfs_period_us").read_text())
    return {"version": 1, "memory_limit_bytes": limit, "memory_current_bytes": used,
            "inactive_file_bytes": inactive,
            "memory_available_bytes": max(0, min(limit, limit - used + inactive)) if limit is not None and used is not None else None,
            "swap_limit_bytes": max(0, memsw - limit) if memsw is not None and limit is not None else None,
            "cpu_limit": quota / period if quota > 0 else None}
