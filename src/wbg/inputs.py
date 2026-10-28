"""Deterministic Stage B input generation, independent of the target key."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def block(role: str, seed: int, counter: int) -> bytes:
    if not 0 <= seed < 2**64 or not 0 <= counter < 2**64:
        raise ValueError("seed/counter must be unsigned 64-bit integers")
    return hashlib.sha256(b"wbg-input-v1\0" + role.encode("ascii") + b"\0" +
                          seed.to_bytes(8, "big") + counter.to_bytes(8, "big")).digest()[:16]


def generate(out: Path, config: dict) -> dict:
    values = config["inputs"]
    seed = values["seed"]
    analysis = [block("analysis", seed, i) for i in range(values["trace_count"])]
    if len(set(analysis)) != len(analysis):
        raise ValueError("analysis input collision")
    holdout = []
    accepted = []
    skipped = []
    counter = 0
    while len(holdout) < values["holdout_count"]:
        candidate = block("holdout", seed, counter)
        if candidate in analysis or candidate in holdout:
            skipped.append(counter)
        else:
            holdout.append(candidate)
            accepted.append(counter)
        counter += 1
    io = [bytes(16), b"\xff" * 16, bytes(range(128, 144))]
    io.extend((1 << bit).to_bytes(16, "big") for bit in range(128))
    io.extend(block("io-check", seed, i) for i in range(16))
    payloads = {"analysis.bin": analysis, "pilot.bin": analysis[:values["pilot_count"]],
                "holdout.bin": holdout, "io-check.bin": io}
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"generator": values["generator"], "seed": seed,
                "analysis_counters": [0, len(analysis) - 1],
                "pilot_source": "first analysis blocks; collect separately",
                "holdout_accepted_counters": accepted, "holdout_skipped_counters": skipped,
                "holdout_disjoint_from_analysis": not bool(set(analysis) & set(holdout)), "files": {}}
    for name, blocks in payloads.items():
        data = b"".join(blocks)
        (out / name).write_bytes(data)
        manifest["files"][name] = {"blocks": len(blocks), "bytes": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
