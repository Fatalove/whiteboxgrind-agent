"""Read-only checks for the pinned local WSL2 toolchain."""

from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from .config import PROJECT
from .resource_advice import advice
from .runtime import BACKEND, container_limits, host_resources


BASELINE = Path(os.environ.get("WBG_BASELINE_PATH", str(PROJECT / "experiments" / "locks" / "stage-b-environment.json")))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _meminfo() -> dict[str, int]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, _, value = line.partition(":")
        if name in {"MemTotal", "SwapTotal"}:
            values[name] = int(value.strip().split()[0]) * 1024
    return values


def check() -> dict:
    """Return concrete checks; no installation, shell setup or process changes."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    work = Path(baseline["work_root"])
    checks = []

    def add(name: str, passed: bool, actual=None, expected=None):
        checks.append({"name": name, "passed": bool(passed), "actual": actual, "expected": expected})

    add("linux", sys.platform == "linux", sys.platform, "linux")
    add("ordinary_user", hasattr(os, "geteuid") and os.geteuid() != 0,
        os.geteuid() if hasattr(os, "geteuid") else None, "non-root")
    add("user", os.environ.get("USER") == "wbg", os.environ.get("USER"), "wbg")
    add("architecture", platform.machine() == "x86_64", platform.machine(), "x86_64")
    release = Path("/etc/os-release").read_text(encoding="utf-8") if Path("/etc/os-release").exists() else ""
    add("ubuntu_22_04", 'ID=ubuntu' in release and 'VERSION_ID="22.04"' in release,
        next((line for line in release.splitlines() if line.startswith("PRETTY_NAME=")), None), "Ubuntu 22.04")
    add("venv_interpreter", Path(sys.executable).resolve() == (work / "venv/bin/python").resolve(),
        str(Path(sys.executable).resolve()), str((work / "venv/bin/python").resolve()))
    if BACKEND == "docker":
        add("container_marker", Path("/.dockerenv").exists(), Path("/.dockerenv").exists(), True)
        try:
            limits = container_limits()
            add("container_cpu_limit", limits["cpu_limit"] == 2, limits["cpu_limit"], 2)
            memory = limits["memory_limit_bytes"]
            swap = limits["swap_limit_bytes"]
            add("container_memory_limit", memory is not None and 0 < memory <= 4 * 2**30, memory, "<= 4 GiB")
            add("container_swap_limit", swap is not None and 0 <= swap <= 2**30, swap, "<= 1 GiB")
        except (OSError, KeyError, ValueError, ZeroDivisionError) as exc:
            add("container_resources", False, repr(exc), "finite cgroup CPU and memory limits")
        try:
            physical = host_resources()
            add("host_physical_resources", True, physical, "fresh physical work/export volume measurements")
        except (OSError, KeyError, ValueError, TypeError) as exc:
            add("host_physical_resources", False, repr(exc), "fresh host observations; sparse volume capacity is insufficient")
    else:
        add("logical_processors", os.cpu_count() == 2, os.cpu_count(), 2)
        try:
            mem = _meminfo()
            add("wsl_memory_limit", 0 < mem["MemTotal"] <= 4 * 2**30, mem["MemTotal"], "<= 4 GiB")
            add("wsl_swap", 900 * 2**20 <= mem["SwapTotal"] <= 1024 * 2**20,
                mem["SwapTotal"], "900-1024 MiB")
        except (OSError, KeyError, ValueError) as exc:
            add("wsl_resources", False, repr(exc), "readable memory and swap")

    patch = PROJECT / "patches" / "0001-tracer-close-input-pipe.patch"
    add("patch_file_sha256", patch.is_file() and _sha256(patch) == baseline["patch_sha256"],
        _sha256(patch) if patch.is_file() else None, baseline["patch_sha256"])
    for name, expected in baseline["file_sha256"].items():
        path = work / name
        actual = _sha256(path) if path.is_file() else None
        add(f"sha256:{name}", actual == expected, actual, expected)
    for name, expected in baseline["python_packages"].items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = None
        add(f"package:{name}", actual == expected, actual, expected)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(work / "prefix/lib") + ":" + env.get("LD_LIBRARY_PATH", "")
    imported = subprocess.run([sys.executable, "-c", "import y5, yaml, numpy, Crypto; print('ok')"],
                              capture_output=True, text=True, env=env, timeout=15)
    add("fresh_process_bindings", imported.returncode == 0 and imported.stdout.strip() == "ok",
        {"exit_code": imported.returncode, "stderr": imported.stderr[-800:]}, "exit 0 and ok")
    return {"command": "doctor", "status": "ready" if all(c["passed"] for c in checks) else "not_ready",
            "ready": all(c["passed"] for c in checks), "checks": checks,
            "baseline": str(BASELINE), "resource_advice": advice(),
            "backend": BACKEND,
            "scope": "read-only deployed backend readiness; not target recovery proof"}
