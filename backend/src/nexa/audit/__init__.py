"""Append-only audit log of every meaningful event.

Why: Lets us reconstruct exactly how a decision was reached (PRD principle 7, section 26).

Where it sits: Layer 1. Written to by tools, approvals and orchestration.
"""
