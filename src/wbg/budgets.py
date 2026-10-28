"""Explicit user-approved group amendments; never erase prior accounting."""
import hashlib
import json
import os
from pathlib import Path

AUTHORIZATIONS = Path(os.environ.get('WBG_BUDGET_AUTHORIZATIONS', str(Path(__file__).resolve().parents[2] / "experiments/budget-authorizations.json")))
INTERACTIVE_AUTHORIZATIONS = Path(os.environ.get('WBG_INTERACTIVE_AUTHORIZATIONS',str(AUTHORIZATIONS.with_name("interactive-authorizations.json"))))


def authorization(config: dict) -> dict | None:
    if not AUTHORIZATIONS.is_file():
        return None
    payload = AUTHORIZATIONS.read_bytes()
    document = json.loads(payload)
    if document.get("schema_version") != 1:
        raise ValueError("invalid budget authorization schema")
    group = f"{config['experiment']}:{config['inputs']['seed']}"
    grant = document.get("groups", {}).get(group)
    path = AUTHORIZATIONS
    if config["resources"]["timeout_seconds"] is None and INTERACTIVE_AUTHORIZATIONS.exists():
        interactive_payload = INTERACTIVE_AUTHORIZATIONS.read_bytes()
        interactive = json.loads(interactive_payload)
        if interactive.get("schema_version") != 1:
            raise ValueError("invalid interactive authorization schema")
        amendment = interactive.get("groups", {}).get(group)
        if amendment and amendment.get("target_sha256") == config["target"]["sha256"].lower():
            grant, payload, path = amendment, interactive_payload, INTERACTIVE_AUTHORIZATIONS
    if grant is None or grant.get("target_sha256") != config["target"]["sha256"].lower():
        return None
    seconds = grant.get("max_total_seconds")
    if (grant.get("approved_by") != "user" or not grant.get("approval_quote") or
            not ((type(seconds) is int and seconds > 0) or
                 (seconds is None and grant.get("time_policy") == "user_controlled")) or
            type(grant.get("max_total_output_bytes")) is not int or grant["max_total_output_bytes"] < 1):
        raise ValueError("invalid explicit budget authorization")
    return {**grant, "group": group, "authorization_path": str(path),
            "authorization_sha256": hashlib.sha256(payload).hexdigest()}
