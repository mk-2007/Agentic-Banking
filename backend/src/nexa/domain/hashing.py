"""Deterministic hashing used for tamper-evident audit records."""

import hashlib
import json


def canonical_json(payload: object) -> str:
    """Serialize ``payload`` to JSON with sorted keys so equal data gives equal text."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(payload: object) -> str:
    """Return the SHA-256 hex digest of the canonical JSON form of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
