"""Roles, permissions and the deterministic policy engine.

Why: Authorization is plain code, never an LLM. It decides what an actor may do (PRD
    principle 3, section 21).

Where it sits: Layer 1. Used by tools and approvals.
"""
