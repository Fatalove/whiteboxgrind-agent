"""Stage B public status and durable JSON helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


EXIT = {"verified": 0, "no_key": 10, "unsupported": 20, "resource_limit": 30,
        "error": 40, "cancelled": 130, "probe_completed": 0}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def response(status: str, reason_code: str | None, **fields) -> dict:
    if status not in EXIT:
        raise ValueError(f"invalid status: {status}")
    return {"schema_version": 1, "status": status, "reason_code": reason_code, **fields}
