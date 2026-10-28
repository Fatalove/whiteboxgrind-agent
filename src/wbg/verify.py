"""Independent AES verifier. No fixture-key import or candidate completion."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

import Crypto
from Crypto.Cipher import AES

VECTORS = [
    ("FIPS-197 AES-128", "000102030405060708090a0b0c0d0e0f", "00112233445566778899aabbccddeeff", "69c4e0d86a7b0430d8cdb78070b4c55a"),
    ("AES-128 zero vector", "00" * 16, "00" * 16, "66e94bd4ef8a2c3b884cfa59ca342b2e"),
    ("SP800-38A F.1.1 first block", "2b7e151628aed2a6abf7158809cf4f3c", "6bc1bee22e409f96e93d7e117393172a", "3ad77bb40d7a3660a89ecaf32466ef97")]


def selftest():
    rows = []
    for label, key, plaintext, expected in VECTORS:
        value = AES.new(bytes.fromhex(key), AES.MODE_ECB).encrypt(bytes.fromhex(plaintext)).hex()
        wrong = bytearray.fromhex(key)
        wrong[0] ^= 1
        rejected = AES.new(bytes(wrong), AES.MODE_ECB).encrypt(bytes.fromhex(plaintext)).hex() != expected
        rows.append({"vector": label, "actual": value, "expected": expected,
                     "passed": value == expected, "deliberately_wrong_key_rejected": rejected})
    return {"scope": "independent verifier selftest only; no target or CPA candidate tested",
            "platform": platform.platform(), "python": sys.version, "pycryptodome": Crypto.__version__,
            "vectors": rows, "passed": all(row["passed"] and row["deliberately_wrong_key_rejected"] for row in rows)}


def validate(candidate_file, plaintexts_file, ciphertexts_file, analysis_file):
    record = json.loads(candidate_file.read_text(encoding="utf-8"))
    # The candidate extractor must provide provenance; this verifier never supplies a known key.
    key = bytes.fromhex(record["key_hex"])
    if len(key) != 16 or not record.get("cpa_csv_sha256"):
        raise ValueError("require a complete 16-byte candidate and CPA provenance")
    plaintexts = plaintexts_file.read_bytes()
    ciphertexts = ciphertexts_file.read_bytes()
    analysis = analysis_file.read_bytes()
    if len(plaintexts) != 16 * 16 or len(ciphertexts) != 16 * 16 or not analysis or len(analysis) % 16:
        raise ValueError("require exactly 16 target holdout pairs and nonempty analysis blocks")
    training = {analysis[i:i+16] for i in range(0, len(analysis), 16)}
    holdouts = [plaintexts[i:i+16] for i in range(0, len(plaintexts), 16)]
    if len(set(holdouts)) != 16 or training.intersection(holdouts):
        raise ValueError("holdout overlap or duplicate")
    rows = []
    cipher = AES.new(key, AES.MODE_ECB)
    for index, plaintext in enumerate(holdouts):
        actual = cipher.encrypt(plaintext)
        expected = ciphertexts[index*16:(index+1)*16]
        rows.append({"index": index, "plaintext": plaintext.hex(), "target_ciphertext": expected.hex(),
                     "independent_ciphertext": actual.hex(), "passed": actual == expected})
    kat = selftest()
    passed = sum(row["passed"] for row in rows)
    return {"scope": "independent candidate holdout verification", "verifier_selftest_passed": kat["passed"],
            "candidate_sha256": hashlib.sha256(candidate_file.read_bytes()).hexdigest(),
            "pycryptodome": Crypto.__version__, "holdout_count": 16, "passed_count": passed,
            "verified": kat["passed"] and passed == 16, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["selftest", "candidate"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--plaintexts", type=Path)
    parser.add_argument("--ciphertexts", type=Path)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    if args.mode == "candidate" and not all((args.candidate, args.plaintexts, args.ciphertexts, args.analysis)):
        parser.error("candidate mode requires --candidate, --plaintexts, --ciphertexts and --analysis")
    result = selftest() if args.mode == "selftest" else validate(args.candidate, args.plaintexts, args.ciphertexts, args.analysis)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get("passed", result.get("verified")) else 1)
