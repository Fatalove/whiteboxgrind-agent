"""Integrity and numeric checks that do not select or accept a candidate."""

import csv
import hashlib
import json
import math
from pathlib import Path
import struct


def absolute_correlation(observed, predicted) -> dict:
    import numpy as np
    a, b = np.asarray(observed, dtype=float), np.asarray(predicted, dtype=float)
    if a.ndim != 1 or a.shape != b.shape or len(a) < 2 or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError("invalid correlation inputs")
    a, b = a - a.mean(), b - b.mean()
    left, right = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return {"absolute_correlation": abs(float(np.dot(a, b) / (left * right))) if left and right else 0.0,
            "observed_zero_variance": not bool(left), "predicted_zero_variance": not bool(right)}


def y5_header(path: Path) -> dict:
    """Guard the pinned v1 header before the native reader can mmap a short file."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        data = stream.read(32)
    if len(data) != 32:
        raise ValueError("invalid_y5_header: shorter than 32 bytes")
    magic, version, flags, entry_size, rows, columns, resolution, capacity = struct.unpack("<IBBHQQII", data)
    if (magic != 0x056c6f79 or version != 1 or flags & 0xf8 or entry_size == 0 or
            32 + 8 * capacity > size or (capacity and not resolution)):
        raise ValueError("invalid_y5_header: magic/version/flags/directory bounds")
    return {"bytes": size, "entry_size": entry_size, "rows": rows, "max_columns": columns}


def input_integrity(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        data = (folder / name).read_bytes()
        if (len(data) != expected["bytes"] or len(data) != expected["blocks"] * 16 or
                hashlib.sha256(data).hexdigest() != expected["sha256"]):
            raise ValueError(f"input_hash_mismatch: {name}")
    def blocks(name):
        data = (folder / name).read_bytes()
        return [data[i:i + 16] for i in range(0, len(data), 16)]
    analysis, holdout = blocks("analysis.bin"), blocks("holdout.bin")
    if (len(analysis) != len(set(analysis)) or len(holdout) != len(set(holdout)) or
            set(analysis) & set(holdout) or
            blocks("pilot.bin") != analysis[:manifest["files"]["pilot.bin"]["blocks"]] or
            not 10 <= manifest["files"]["pilot.bin"]["blocks"] <= len(analysis)):
        raise ValueError("input_partition_invalid")
    return {"passed": True, "hashes_checked": len(manifest["files"]),
            "holdout_disjoint": True, "pilot_is_analysis_prefix": True}


def csv_integrity(path: Path, feature_count: int) -> dict:
    if feature_count <= 0:
        raise ValueError("no measured features")
    seen = set()
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["key_byte", "guess", "best_correlation", "best_sample"]:
            raise ValueError("invalid CSV header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("malformed CSV row")
            byte, guess, sample = int(row["key_byte"]), int(row["guess"]), int(row["best_sample"])
            score = float(row["best_correlation"])
            if not (0 <= byte < 16 and 0 <= guess < 256 and 0 <= sample < feature_count):
                raise ValueError("CSV index outside measured range")
            if not math.isfinite(score) or abs(score) > 1.000001:
                raise ValueError("nonfinite or invalid CSV correlation")
            if (byte, guess) in seen:
                raise ValueError("duplicate CSV byte/guess")
            seen.add((byte, guess))
    if len(seen) != 4096:
        raise ValueError(f"CSV rows: expected 4096, got {len(seen)}")
    return {"passed": True, "rows": 4096, "selection_performed": False}
