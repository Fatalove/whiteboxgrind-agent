"""Parse pinned Whiteboxgrind CPA CSV without loading any reference key."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def extract(path, feature_count):
    if feature_count <= 0:
        raise ValueError("must establish a positive leakage feature count first")
    rows = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["key_byte", "guess", "best_correlation", "best_sample"]:
            raise ValueError("unexpected CPA CSV header")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed row at line {line}")
            byte, guess = int(row["key_byte"]), int(row["guess"])
            score, sample = float(row["best_correlation"]), int(row["best_sample"])
            if not (0 <= byte < 16 and 0 <= guess < 256):
                raise ValueError(f"invalid byte/guess at line {line}")
            if not math.isfinite(score) or abs(score) > 1.000001:
                raise ValueError(f"invalid correlation at line {line}")
            if not 0 <= sample < feature_count:
                raise ValueError(f"sample index outside measured feature range at line {line}")
            if (byte, guess) in rows:
                raise ValueError(f"duplicate byte/guess at line {line}")
            rows[byte, guess] = {"key_byte": byte, "guess": guess, "correlation": score,
                                 "best_sample": sample, "csv_line": line}
    if len(rows) != 16 * 256:
        raise ValueError(f"require 4096 rows, got {len(rows)}")
    selected = []
    for byte in range(16):
        options = [rows[byte, guess] for guess in range(256)]
        largest = max(abs(row["correlation"]) for row in options)
        ties = [row for row in options if abs(row["correlation"]) == largest]
        chosen = dict(min(ties, key=lambda row: row["guess"]))
        chosen["tied_guesses"] = [row["guess"] for row in ties]
        selected.append(chosen)
    return {"key_hex": bytes(row["guess"] for row in selected).hex(),
            "cpa_csv": str(path.resolve()), "cpa_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "csv_rows": len(rows), "feature_count": feature_count,
            "selection": "maximum absolute correlation; exact ties choose lower guess", "bytes": selected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--feature-count", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.csv, args.feature_count)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("Complete CPA candidate saved locally; independent holdout verification is still required.")
