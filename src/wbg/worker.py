"""One bounded Stage B target run inside the supervisor's process group."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np
import y5
from Crypto.Cipher import AES

from .config import PROJECT
from .protocol import atomic_json
from .runtime import ENGINE_ROOT
from .checks import input_integrity, csv_integrity, y5_header, absolute_correlation
from .workflow import quote, enter_stage, read as read_control


# Keep the proven Stage A candidate and independent verifier implementations intact.
from .candidate import extract
from .verify import selftest, validate


WORK = ENGINE_ROOT
PREFIX = WORK / "prefix"
RESOURCES = PROJECT / "fixtures" / "stage-b-aes128" / "resources"
ENTRY = np.dtype([("sync", "<u8"), ("pc", "<u8"), ("addr", "<u8"),
                  ("width", "<u4"), ("endianness", "u1"), ("mode", "u1"),
                  ("value", "u1", (34,))], align=False)
STRUCTURE = np.dtype([("pc", "<u8"), ("width", "<u4"),
                      ("endianness", "u1"), ("mode", "u1")], align=False)
POPCOUNT = np.array([value.bit_count() for value in range(256)], dtype=np.uint8)


class PipelineError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code


def _blocks(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if not data or len(data) % 16:
        raise PipelineError("invalid_input_blocks", str(path))
    return [data[index:index + 16] for index in range(0, len(data), 16)]


def _row(reader) -> bytes:
    parts = []
    while True:
        array, done = reader.read(4096)
        parts.append(array.tobytes())
        if done:
            return b"".join(parts)
        if not array.size:
            raise PipelineError("y5_no_progress", "Y5 reader made no progress")


def _summary(path: Path) -> dict:
    reader = _reader(path)
    return {"path": str(path), "bytes": path.stat().st_size,
            "entry_size": reader.entry_size, "rows": reader.rows,
            "max_columns": reader.max_columns, "flags": int(reader.flags)}


def _reader(path: Path):
    try:
        y5_header(path)
        return y5.reader(str(path))
    except Exception as exc:
        raise PipelineError("invalid_y5", f"{path}: {exc}") from exc


class Worker:
    def __init__(self, run: Path):
        self.run = run.resolve(strict=True)
        self.config = json.loads((run / "effective-config.json").read_text(encoding="utf-8"))
        self.stage = "initialization"
        self.started = time.monotonic()
        self.commands = []
        self.metrics = {}

    def save(self, path: Path, value: dict | list) -> None:
        if path.exists():
            raise FileExistsError(path)
        atomic_json(path, value)

    def stage_record(self, name: str) -> None:
        enter_stage(self.run, name)
        self.stage = name

    def command(self, name: str, argv: list, *, cwd: Path | None = None,
                env: dict | None = None, allow_failure: bool = False) -> dict:
        self.stage_record(name)
        folder = self.run / "logs" / name
        folder.mkdir(parents=True, exist_ok=False)
        before = time.monotonic()
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            process = subprocess.run([str(item) for item in argv], cwd=cwd, env=env,
                                     stdout=stdout, stderr=stderr)
        record = {"argv": [str(item) for item in argv], "cwd": str(cwd) if cwd else None,
                  "exit_code": process.returncode,
                  "elapsed_seconds": round(time.monotonic() - before, 3),
                  "stdout": str(folder / "stdout.log"), "stderr": str(folder / "stderr.log")}
        self.save(folder / "command.json", record)
        self.commands.append({"name": name, **record})
        atomic_json(self.run / "commands.json", {"commands": self.commands})
        if process.returncode and not allow_failure:
            raise PipelineError("command_failed", f"{name} exited {process.returncode}; see {folder}")
        return record

    def native(self, binary: Path, values: list[bytes], name: str, instrumented: bool = False) -> tuple[list, list[bytes]]:
        self.stage_record(name)
        rows = []
        output = []
        argv = ([str(PREFIX / "bin/valgrind"), "--tool=whiteboxgrind", "--client-requests=yes",
                 "--trace-instructions=no", "--trace-memory=no", str(binary)] if instrumented else [str(binary)])
        for index, data in enumerate(values):
            before = time.monotonic()
            process = subprocess.run(argv, input=data, capture_output=True)
            rows.append({"index": index, "input_bytes": len(data), "input_hex": data.hex(),
                         "exit_code": process.returncode, "stdout_hex": process.stdout.hex(),
                         "stderr": process.stderr.decode(errors="replace"),
                         "elapsed_seconds": round(time.monotonic() - before, 3)})
            output.append(process.stdout)
        self.save(self.run / "checks" / f"{name}.json", {"argv": argv, "rows": rows,
                  "scope": "instrumented I/O only; event capture disabled" if instrumented else "native block I/O"})
        return rows, output

    def probe(self, direct: Path | None) -> dict:
        input_file = self.run / "probe-input.bin"
        input_file.write_bytes(_blocks(self.run / "inputs/analysis.bin")[0])
        data = _blocks(input_file)
        rows, expected = self.native(self.run / "target/target", data, "probe-native")
        if direct:
            direct_rows, direct_output = self.native(direct, data, "probe-direct")
            if direct_output != expected or direct_rows[0]["exit_code"]:
                raise PipelineError("probe_direct_mismatch", "original and wrapped single input differ")
        folder, observed, timing = self.trace("probe", input_file)
        if rows[0]["exit_code"] or len(expected[0]) != 16 or observed != expected:
            raise PipelineError("probe_io_mismatch", "single trace differs from native output")
        structure = self.inspect_reads(folder / "probe-read.y5", 1, "probe-reads")
        record = {"scope": "single full trace diagnosis; no CPA or recovery attempted", "collected_count": 1,
                  "collection_seconds": timing["elapsed_seconds"], "structure": structure,
                  "products": [{"path": str(p.relative_to(self.run)), "bytes": p.stat().st_size}
                               for p in sorted(folder.rglob("*")) if p.is_file()]}
        self.save(self.run / "probe.json", record)
        return {"status": "probe_completed", "reason_code": None, "completed_stage": "probe-reads",
                "execution": {"status": "passed"}, "recovery": {"status": "not_attempted"},
                "metrics": {"collected_count": 1, "collection_seconds": timing["elapsed_seconds"]}}

    def trace(self, name: str, input_file: Path) -> tuple[Path, list[bytes], dict]:
        folder = self.run / name
        folder.mkdir(exist_ok=False)
        artifacts = folder / "target-build"
        artifacts.mkdir()
        env = dict(os.environ, TMPDIR=str(self.run / "tmp"),
                   WBG_AES_SOURCE_DIR=str(WORK / "src/tiny-AES-c"),
                   WBG_ORIGINAL_SOURCE=str(self.run / "target/source.c"),
                   WBG_EXTRA_AES="1" if self.config["target"].get("fixture") == "ordinary-aes128" else "0",
                   WBG_TARGET_ARTIFACT_DIR=str(artifacts))
        timing = self.command(name + "-collect",
                              [PREFIX / "bin/tracer", "--inputs", input_file,
                               "--name", name + "-", "--resources", RESOURCES,
                               self.run / "target/wrapper.c", folder, PREFIX / "bin/valgrind"], env=env)
        values = _reader(folder / (name + "-values.y5"))
        expected = _blocks(input_file)
        if values.entry_size != 32 or values.rows != len(expected) or values.max_columns != 1:
            raise PipelineError("invalid_values_y5", f"invalid values structure for {name}")
        ciphertexts = []
        for index, plaintext in enumerate(expected):
            pair = _row(values)
            if len(pair) != 32 or pair[:16] != plaintext:
                raise PipelineError("plaintext_mapping", f"{name} input {index}")
            ciphertexts.append(pair[16:])
        return folder, ciphertexts, timing

    def _structure_difference(self, path: Path, other_row: int) -> dict:
        left = _reader(path)
        right = _reader(path)
        left.seek(0)
        right.seek(other_row)
        offset = 0
        while True:
            a, done_a = left.read(4096)
            b, done_b = right.read(4096)
            av = np.frombuffer(a.tobytes(), dtype=ENTRY)
            bv = np.frombuffer(b.tobytes(), dtype=ENTRY)
            limit = min(len(av), len(bv))
            for index in range(limit):
                fields = ("pc", "width", "endianness", "mode")
                if any(int(av[field][index]) != int(bv[field][index]) for field in fields):
                    return {"row": other_row, "event": offset + index,
                            "first": {field: int(av[field][index]) for field in fields},
                            "other": {field: int(bv[field][index]) for field in fields}}
            if len(av) != len(bv) or done_a != done_b:
                return {"row": other_row, "event": offset + limit,
                        "first_chunk_length": len(av), "other_chunk_length": len(bv)}
            if done_a and done_b:
                return {"row": other_row, "event": None, "detail": "digest differed without field mismatch"}
            offset += limit

    def inspect_reads(self, path: Path, count: int, name: str) -> dict:
        self.stage_record(name)
        reader = _reader(path)
        if reader.entry_size != ENTRY.itemsize or reader.rows != count:
            raise PipelineError("invalid_read_y5", str(path))
        if reader.max_columns == 0:
            raise PipelineError("empty_raw_trace", str(path))
        first_digest = None
        counts = []
        examples = []
        for trace in range(count):
            digest = hashlib.sha256()
            events = 0
            done = False
            while not done:
                array, done = reader.read(4096)
                data = np.frombuffer(array.tobytes(), dtype=ENTRY)
                if not len(data) and not done:
                    raise PipelineError("y5_no_progress", f"{name} trace {trace}")
                if np.any(data["mode"] != 0) or np.any(data["width"] < 1) or np.any(data["width"] > 34):
                    raise PipelineError("invalid_read_metadata", f"{name} trace {trace}")
                if len(data):
                    padding = np.arange(34)[None, :] >= data["width"][:, None]
                    if np.any((data["value"] != 0) & padding):
                        raise PipelineError("nonzero_read_padding", f"{name} trace {trace}")
                    hw = POPCOUNT[data["value"]].sum(axis=1, dtype=np.uint16)
                    if np.any(hw > 255):
                        raise PipelineError("hamming_weight_overflow", f"{name} trace {trace}")
                    structure = np.empty(len(data), dtype=STRUCTURE)
                    for field in STRUCTURE.names:
                        structure[field] = data[field]
                    digest.update(structure.tobytes())
                    if trace < 2 and len(examples) < 6:
                        for index in np.flatnonzero(hw)[:3]:
                            entry = data[index]
                            examples.append({"trace": trace, "event": events + int(index),
                                             "pc": hex(int(entry["pc"])),
                                             "width": int(entry["width"]),
                                             "value_hex": entry["value"].tobytes().hex(),
                                             "full_buffer_hw": int(hw[index])})
                events += len(data)
            if not events:
                raise PipelineError("empty_raw_trace", f"{name} trace {trace}")
            current = digest.hexdigest()
            if first_digest is None:
                first_digest = current
            elif current != first_digest or events != counts[0]:
                detail = self._structure_difference(path, trace)
                self.save(self.run / "checks" / f"{name}-structure-diff.json", detail)
                raise PipelineError("fixed_path_structure_mismatch", json.dumps(detail))
            counts.append(events)
        result = {"file": _summary(path), "event_counts": counts,
                  "pc_width_mode_sequences_aligned": True,
                  "address_values_not_used_as_alignment_rejection": True,
                  "padding_zero_checked": True, "uint8_overflow_observed": False,
                  "structure_sha256": first_digest, "examples": examples}
        self.save(self.run / "checks" / f"{name}.json", result)
        return result

    def process(self, raw: Path, count: int, folder: Path, name: str, *, candidate: bool) -> dict:
        analysis = self.config["analysis"]
        folder.mkdir(exist_ok=False)
        common = ["--threads", str(analysis["threads"]), "--block-size", str(analysis["block_size"]),
                  "--max-live-blocks", str(analysis["max_live_blocks"])]
        self.command(name + "-filter", [PREFIX / "bin/filter", *common, "--max-row-memory",
                        str(analysis["filter_max_row_memory_kib"]), raw / (raw.name + "-read.y5"), folder / "filtered.y5"])
        self.command(name + "-unique", [PREFIX / "bin/unique", *common, "--cache-size",
                        str(analysis["unique_cache_size"]), folder / "filtered.y5", folder / "unique.y5"])
        self.command(name + "-leakage", [PREFIX / "bin/leakage", *common, "--max-row-memory",
                        str(analysis["leakage_max_row_memory_kib"]), "--model", analysis["leakage_model"],
                        folder / "unique.y5", folder / "leakage.y5"])
        unique = _reader(folder / "unique.y5")
        leakage = _reader(folder / "leakage.y5")
        if unique.entry_size != 64 or leakage.entry_size != 1 or unique.rows != leakage.rows:
            raise PipelineError("invalid_processed_structure", name)
        if not unique.rows:
            raise PipelineError("no_features", name)
        varying = 0
        examples = []
        for index in range(unique.rows):
            data = np.frombuffer(_row(unique), dtype=ENTRY)
            observed = np.frombuffer(_row(leakage), dtype=np.uint8)
            if len(data) != count or len(observed) != count:
                raise PipelineError("processed_count_mismatch", f"{name} feature {index}")
            expected = POPCOUNT[data["value"]].sum(axis=1, dtype=np.uint16)
            if np.any(expected > 255) or not np.array_equal(expected, observed):
                raise PipelineError("native_hamming_weight_mismatch", f"{name} feature {index}")
            if np.any(observed != observed[0]):
                varying += 1
                if len(examples) < 3:
                    first = data[0]
                    examples.append({"feature": index, "pc": hex(int(first["pc"])),
                                     "width": int(first["width"]),
                                     "first_value_hex": first["value"].tobytes().hex(),
                                     "observed_hw_first_10": observed[:10].tolist()})
        metrics = {"features": unique.rows, "varying_features": varying,
                   "zero_variance_features": unique.rows - varying,
                   "native_hw_matches_all_values": True, "examples": examples}
        self.save(self.run / "checks" / f"{name}-leakage-semantics.json", metrics)
        if not varying:
            raise PipelineError("no_observable_variation" if candidate else "no_varying_features", name)
        csv_path = (self.run / "cpa.csv") if candidate else (folder / "pilot-cpa.csv")
        self.command(name + "-cpa", [PREFIX / "bin/cpa", *common, "--chunk-key-bytes",
                        str(analysis["chunk_key_bytes"]), "--selection-function",
                        analysis["selection_function"], "--output", csv_path,
                        folder / "leakage.y5", raw / (raw.name + "-values.y5")])
        if not csv_path.is_file() or not csv_path.stat().st_size:
            raise PipelineError("empty_cpa_csv", name)
        self.save(self.run / "checks" / f"{name}-csv-integrity.json", csv_integrity(csv_path, unique.rows))
        metrics["cpa_csv_bytes"] = csv_path.stat().st_size
        metrics["cpa_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        return metrics

    def execute(self) -> dict:
        if os.geteuid() == 0 or ENTRY.itemsize != 64:
            raise PipelineError("environment_invalid", "requires ordinary Linux user and 64-byte trace entries")
        self.run.joinpath("tmp").mkdir(exist_ok=False)
        self.save(self.run / "checks/input-integrity.json", input_integrity(self.run / "inputs"))
        kat = selftest()
        self.save(self.run / "checks/verifier-selftest.json", kat)
        if not kat["passed"]:
            raise PipelineError("verifier_selftest_failed", "three known-answer vectors failed")
        target = self.run / "target"
        env = dict(os.environ, WBG_ORIGINAL_SOURCE=str(target / "source.c"),
                   WBG_AES_SOURCE_DIR=str(WORK / "src/tiny-AES-c"),
                   WBG_EXTRA_AES="1" if self.config["target"].get("fixture") == "ordinary-aes128" else "0",
                   MORE_INCDIR=str(PREFIX / "include/valgrind"))
        self.command("native-build", ["make", "-j1"], cwd=target, env=env)
        probing = read_control(self.run, "operation.json", {}).get("command") == "probe"
        if probing and self.config["target"].get("fixture"):
            return self.probe(None)
        # Compile a separate driver that declares and calls the original ABI directly.
        # Only our harness text is adapted; the target source bytes are untouched.
        if not self.config["target"].get("fixture"):
            pointer = "char" if self.config["target"]["abi"] == "char-pointer" else "unsigned char"
            direct_main = (target / "main.c").read_text().replace(
                "void wbg_encrypt_block(unsigned char out[16], unsigned char in[16]);",
                f"void AES_128_encrypt({pointer} *out, {pointer} *in);").replace(
                "wbg_encrypt_block(out, in);", f"AES_128_encrypt(({pointer} *)out, ({pointer} *)in);")
            (target / "direct-main.c").write_text(direct_main)
            self.command("direct-build", ["cc", *self.config["target"]["compile_flags"],
                         "-I" + str(PREFIX / "include/valgrind"), target / "direct-main.c",
                         target / "source.c", "-o", target / "direct-target"])
            if probing:
                return self.probe(target / "direct-target")
            direct_rows, direct_output = self.native(target / "direct-target",
                                                     _blocks(self.run / "inputs/io-check.bin"), "io-direct")
            if not all(row["exit_code"] == 0 and len(value) == 16
                       for row, value in zip(direct_rows, direct_output)):
                raise PipelineError("direct_io_invalid", "147 direct original ABI calls must return 16 bytes")
        missing = self.run / "checks/missing-header"
        missing.mkdir()
        for name in ("main.c", "Makefile", "wrapper.c", "source.c"):
            shutil.copyfile(target / name, missing / name)
        (missing / "empty-include").mkdir()
        bad_env = dict(env, WBG_ORIGINAL_SOURCE=str(missing / "source.c"),
                       MORE_INCDIR=str(missing / "empty-include"))
        refusal = self.command("missing-header-build", ["make", "-j1"], cwd=missing,
                               env=bad_env, allow_failure=True)
        if refusal["exit_code"] == 0 or (missing / "target").exists():
            raise PipelineError("missing_header_accepted", "trace header absence was not rejected")
        io_rows, native_io = self.native(target / "target", _blocks(self.run / "inputs/io-check.bin"), "io-native")
        if not all(row["exit_code"] == 0 and len(value) == 16
                   for row, value in zip(io_rows, native_io)):
            raise PipelineError("native_io_invalid", "147 native calls must return 16 bytes")
        if self.config["target"].get("fixture") == "ordinary-aes128":
            reference = AES.new(bytes(range(16)), AES.MODE_ECB)
            if any(value != reference.encrypt(bytes.fromhex(row["input_hex"]))
                   for row, value in zip(io_rows, native_io)):
                raise PipelineError("fixture_reference_mismatch", "ordinary AES native I/O differs from independent AES")
        invalid, _ = self.native(target / "target", [b"", bytes(15), bytes(17)], "strict-length-negative")
        if not all(row["exit_code"] == 2 and not row["stdout_hex"] for row in invalid):
            raise PipelineError("strict_length_rejection_failed", "0/15/17 input accepted")
        instrumented_rows, traced_io = self.native(target / "target", _blocks(self.run / "inputs/io-check.bin"),
                                                   "io-instrumented", instrumented=True)
        if not all(row["exit_code"] == 0 for row in instrumented_rows):
            raise PipelineError("instrumented_io_failed", "I/O-only Valgrind invocation failed")
        if traced_io != native_io:
            raise PipelineError("instrumented_io_mismatch", "147 native/instrumented outputs differ")
        if not self.config["target"].get("fixture"):
            if direct_output != native_io:
                raise PipelineError("direct_wrapper_io_mismatch", "direct ABI and wrapped outputs differ")
            self.save(self.run / "checks/io-three-way.json", {
                "count": len(native_io), "passed": True, "each_output_bytes": 16,
                "paths": ["io-direct.json", "io-native.json", "io-instrumented.json"],
                "source_sha256_after": hashlib.sha256((target / "source.c").read_bytes()).hexdigest(),
                "scope": "original ABI driver / separate wrapper / actual Valgrind I/O; full events checked in pilot/formal"})
        pilot, pilot_output, pilot_timing = self.trace("pilot", self.run / "inputs/pilot.bin")
        self.inspect_reads(pilot / "pilot-read.y5", self.config["inputs"]["pilot_count"], "pilot-reads")
        pilot_rows, native_pilot = self.native(target / "target", _blocks(self.run / "inputs/pilot.bin"), "pilot-native")
        if pilot_output != native_pilot or not all(row["exit_code"] == 0 for row in pilot_rows):
            raise PipelineError("pilot_io_mismatch", "native/instrumented pilot outputs differ")
        try:
            pilot_metrics = self.process(pilot, self.config["inputs"]["pilot_count"], self.run / "pilot-processed",
                                         "pilot", candidate=False)
        except PipelineError as exc:
            raise PipelineError("pilot_cost_unavailable", f"{exc.reason_code}: {exc}") from exc
        pilot_bytes = sum(path.stat().st_size for folder in (pilot, self.run / "pilot-processed")
                          for path in folder.rglob("*") if path.is_file())
        occupied = sum(path.stat().st_size for path in self.run.rglob("*") if path.is_file())
        estimate = quote(self.commands, self.config["inputs"]["pilot_count"],
                         self.config["inputs"]["trace_count"], pilot_bytes, occupied,
                         self.config["resources"]["output_limit_mib"] * 2**20)
        checkpoint = {"io": "checks/io-three-way.json" if not self.config["target"].get("fixture") else "checks/io-native.json",
                      "pilot_structure": "checks/pilot-reads.json", "pilot_metrics": pilot_metrics,
                      "estimate": estimate, "warnings": self.tool_warnings(),
                      "conclusion": "await user decision before full formal collection",
                      "boundary": "Pilot is a cost/semantic probe, not a formal recovery result."}
        self.save(self.run / "checks/pilot-checkpoint.json", checkpoint)
        self.stage_record("awaiting_formal_approval")
        self.save(self.run / "estimate.json", estimate)
        (self.run / "report.md").write_text("# Pilot checkpoint\n\n```json\n" +
                                            json.dumps(checkpoint, indent=2) + "\n```\n", encoding="utf-8")
        # No raw-data reuse or native analysis while waiting. The supervisor
        # enforces decision timeout, cancellation, disk limits and hard deadline.
        enter_stage(self.run, "formal-start", require_formal=True)
        raw, raw_output, _ = self.trace("raw", self.run / "inputs/analysis.bin")
        self.inspect_reads(raw / "raw-read.y5", self.config["inputs"]["trace_count"], "formal-reads")
        formal_rows, native_formal = self.native(target / "target", _blocks(self.run / "inputs/analysis.bin"), "formal-native")
        if raw_output != native_formal or not all(row["exit_code"] == 0 and len(value) == 16
                                                for row, value in zip(formal_rows, native_formal)):
            raise PipelineError("formal_io_mismatch", "native/instrumented formal outputs differ")
        metrics = self.process(raw, self.config["inputs"]["trace_count"], self.run / "processed",
                               "formal", candidate=True)
        self.metrics = metrics
        self.stage_record("independent_holdout")
        candidate = extract(self.run / "cpa.csv", metrics["features"])
        self.save(self.run / "candidate.json", candidate)
        source = (WORK / "src/whiteboxgrind/cpp/cpa.h").read_text()
        table = source.split("AES_SBOX[] = {", 1)[1].split("};", 1)[0]
        sbox = np.array([int(value, 16) for value in re.findall(r"0x[0-9a-fA-F]+", table)], dtype=np.uint8)
        if len(sbox) != 256:
            raise PipelineError("invalid_sbox", "pinned source SBox extraction failed")
        plaintext = np.frombuffer((self.run / "inputs/analysis.bin").read_bytes(), dtype=np.uint8).reshape(-1, 16)
        leakage = _reader(self.run / "processed/leakage.y5")
        correlations = []
        for selected in candidate["bytes"]:
            leakage.seek(selected["best_sample"])
            observed = np.frombuffer(_row(leakage), dtype=np.uint8).astype(float)
            predicted = POPCOUNT[sbox[plaintext[:, selected["key_byte"]] ^ selected["guess"]]].astype(float)
            calculation = absolute_correlation(observed, predicted)
            score = calculation["absolute_correlation"]
            row = {"key_byte": selected["key_byte"], "sample": selected["best_sample"],
                   "numpy_absolute_correlation": score, "csv_correlation": selected["correlation"],
                   "zero_variance": calculation["observed_zero_variance"] or calculation["predicted_zero_variance"],
                   "variance_diagnostics": calculation,
                   "passed": math.isfinite(score) and abs(score - abs(selected["correlation"])) <= 0.00001}
            correlations.append(row)
        self.save(self.run / "checks/independent-correlations.json", correlations)
        if not all(row["passed"] for row in correlations):
            raise PipelineError("correlation_mismatch", "selected CSV scores do not match independent calculation")
        holdout_rows, holdout = self.native(target / "target", _blocks(self.run / "inputs/holdout.bin"), "holdout-target")
        if not all(row["exit_code"] == 0 and len(value) == 16 for row, value in zip(holdout_rows, holdout)):
            raise PipelineError("holdout_target_io_invalid", "holdout target did not produce 16-byte blocks")
        (self.run / "holdout-ciphertexts.bin").write_bytes(b"".join(holdout))
        validation = validate(self.run / "candidate.json", self.run / "inputs/holdout.bin",
                              self.run / "holdout-ciphertexts.bin", self.run / "inputs/analysis.bin")
        self.save(self.run / "validation.json", validation)
        wrong = dict(candidate)
        bad = bytearray.fromhex(candidate["key_hex"])
        bad[0] ^= 1
        wrong.update(key_hex=bytes(bad).hex(), test_only=True,
                     purpose="deliberately wrong candidate; not a recovery output")
        self.save(self.run / "checks/wrong-candidate.json", wrong)
        negative = validate(self.run / "checks/wrong-candidate.json", self.run / "inputs/holdout.bin",
                            self.run / "holdout-ciphertexts.bin", self.run / "inputs/analysis.bin")
        self.save(self.run / "checks/wrong-candidate-validation.json", negative)
        if negative["verified"]:
            raise PipelineError("negative_candidate_accepted", "test-only wrong candidate was accepted")
        return {"status": "verified" if validation["verified"] else "no_key",
                "reason_code": None if validation["verified"] else "candidate_failed_holdout",
                "completed_stage": "independent_holdout", "execution": {"status": "passed"},
                "recovery": {"status": "verified" if validation["verified"] else "not_recovered",
                             "holdout_passed": validation["passed_count"], "holdout_total": 16},
                "metrics": metrics, "io_pairs_checked": 147,
                "elapsed_seconds": round(time.monotonic() - self.started, 3)}

    def tool_warnings(self) -> dict:
        matches = []
        for path in sorted((self.run / "logs").rglob("*.log")):
            for line in path.read_text(errors="replace").splitlines():
                if any(term in line.lower() for term in ("warn", "rseq", "dwarf", "evict", "cache")):
                    matches.append({"path": str(path.relative_to(self.run)), "line": line[:500]})
        cache = [item for item in matches if any(word in item["line"].lower() for word in ("cache", "evict", "discard"))]
        return {"observed_log_lines": matches[:80], "matching_line_count": len(matches), "general_list_truncated": len(matches) > 80,
                "cache_warning_lines": cache, "cache_eviction_count": None,
                "cache_note": "finite cache; no claim of global deduplication"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    worker = Worker(args.run)
    try:
        result = worker.execute()
    except PipelineError as exc:
        status = ("resource_limit" if exc.reason_code == "pilot_budget_gate" else
                  "no_key" if exc.reason_code == "no_observable_variation" else
                  "unsupported" if exc.reason_code == "fixed_path_structure_mismatch" else "error")
        result = {"status": status,
                  "reason_code": exc.reason_code, "completed_stage": worker.stage,
                  "execution": {"status": "passed" if status == "no_key" else "incomplete"},
                  "recovery": {"status": "not_recovered" if status == "no_key" else "not_attempted"},
                  "error": str(exc), "elapsed_seconds": round(time.monotonic() - worker.started, 3)}
        traceback.print_exc()
    except Exception as exc:
        result = {"status": "error", "reason_code": "worker_exception", "completed_stage": worker.stage,
                  "execution": {"status": "incomplete"}, "recovery": {"status": "not_attempted"},
                  "error": repr(exc), "elapsed_seconds": round(time.monotonic() - worker.started, 3)}
        traceback.print_exc()
    atomic_json(worker.run / "worker-result.json", result)
    atomic_json(worker.run / "commands.json", {"commands": worker.commands})
    return {"verified": 0, "probe_completed": 0, "no_key": 10, "unsupported": 20,
            "resource_limit": 30, "error": 40}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
