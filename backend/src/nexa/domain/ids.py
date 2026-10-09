"""Identifier helpers."""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Return a short readable unique id such as ``case_3f9a1c2b7d4e``."""
    return f"{prefix}_{uuid4().hex[:12]}"
